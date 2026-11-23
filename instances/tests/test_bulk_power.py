"""Start, shut down or force off the VMs chosen on the VM list: a job each
(instance.start, .shutdown, .force_off), so each VM is held, checked when it
runs and recovered on its own, with its own log row and its action named on
the Jobs page. A VM the user may not power, or
that another job holds, is named and the others are queued. Who may power a
VM may choose it, as on its own page."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase
from django.urls import reverse
from lxml import html

from accounts.models import UserInstance
from computes.models import Compute
from instances.jobs import ForceOffVM, ShutdownVM, StartVM
from instances.models import Instance
from operations import claims
from operations.jobs import Context
from operations.models import Claim, Operation, acquire
from vrtManager.util import OperationError


class BulkPowerTestCase(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("bp-admin", "bp@example.com", "pw")
        self.client.force_login(self.admin)
        compute = Compute.objects.create(name="bp-host", hostname="127.0.0.1", login="", password="", type=4)
        self.vms = [Instance.objects.create(compute=compute, name=f"bp-vm{n}", uuid=f"00000000-0000-4000-8000-00000000000{n}")
                    for n in (1, 2)]
        self.proxies = {vm.name: MagicMock(**{"get_status.return_value": 5}) for vm in self.vms}
        patch.object(Instance, "proxy", property(lambda vm: self.proxies[vm.name])).start()
        patch.object(Compute, "refuse_start", lambda compute: None).start()
        self.addCleanup(patch.stopall)

    def submit(self, action, vms, user=None):
        if user:
            self.client.force_login(user)
        self.client.cookies.pop("messages", None)
        response = self.client.post(reverse("instances:bulk_power"), {"action": action, "vm": [vm.pk for vm in vms],
                                                                       "submission_key": "key-bulkpow1"})
        return response, [str(m) for m in get_messages(response.wsgi_request)]

    def run_job(self, op):
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        ctx = Context(op, SimpleNamespace(identity="wvc-test:1:a"))
        kind = {"instance.start": StartVM, "instance.shutdown": ShutdownVM, "instance.force_off": ForceOffVM}[op.kind]()
        kind.precheck(op, ctx)
        return kind.run(op, ctx)

    def test_the_list_queues_a_job_for_each_vm(self):
        response, said = self.submit("start", self.vms)
        self.assertRedirects(response, reverse("operations:jobs") + "?kind=instance.start", fetch_redirect_response=False)
        self.assertEqual(said, ["2 VMs are queued; the Jobs page follows them."])
        ops = list(Operation.objects.order_by("resource_label"))
        self.assertEqual([(op.kind, op.params, op.resource_label) for op in ops],
                         [("instance.start", {"instance": vm.pk}, f"bp-host/{vm.name}") for vm in self.vms])
        # each holds its VM and shares its host, as a job on the VM's page does
        self.assertEqual(set(Claim.objects.filter(operation=ops[0]).values_list("resource", "mode")),
                         {(f"compute:{self.vms[0].compute_id}", "shared"), (f"instance:{self.vms[0].uuid}", "exclusive")})
        # the form sent again queues none twice, and says so as the first time (not "busy")
        _response, said = self.submit("start", self.vms)
        self.assertEqual(said, ["2 VMs are queued; the Jobs page follows them."])
        self.assertEqual(Operation.objects.count(), 2)

    def test_each_job_powers_its_vm(self):
        for proxy in self.proxies.values():
            proxy.get_status.return_value = 1  # running
        self.submit("force_off", self.vms)
        for op in Operation.objects.all():
            self.run_job(op)
        for proxy in self.proxies.values():
            proxy.force_shutdown.assert_called_once_with()
            proxy.start.assert_not_called()

    def test_a_vm_another_job_holds_is_named_and_the_others_queued(self):
        holder = Operation.objects.create(kind="instance.snapshot", user=self.admin, username="bp-admin",
                                          state=Operation.RUNNING, resource="x", resource_label="bp-host/bp-vm1")
        Claim.objects.create(resource=claims.instance_key(self.vms[0].uuid), mode=Claim.EXCLUSIVE, operation=holder)
        _response, said = self.submit("shutdown", self.vms)
        self.assertTrue(said[0].startswith("bp-vm1: "), said)
        self.assertEqual(said[1:], ["1 VM is queued; the Jobs page follows it."])
        self.assertEqual(Operation.objects.get(kind="instance.shutdown").params["instance"], self.vms[1].pk)

    def test_an_action_that_does_not_apply_fails_before_libvirt_is_asked(self):
        # an already shut off VM forced off, a running one started: refused, its claims go with the failed job
        for action, status in (("force_off", 5), ("shutdown", 5), ("start", 1)):
            with self.subTest(action=action):
                Operation.objects.all().delete()
                self.proxies["bp-vm1"].get_status.return_value = status
                self.submit(action, self.vms[:1])
                op = Operation.objects.get()
                with self.assertRaises(OperationError):
                    self.run_job(op)
                op.refresh_from_db()
                self.assertNotIn("powering", op.intent)
        for call in ("start", "shutdown", "force_shutdown"):
            getattr(self.proxies["bp-vm1"], call).assert_not_called()

    def test_recovery_reads_what_libvirt_did(self):
        op = SimpleNamespace(intent={"compute": 1, "uuid": "u", "powering": True})
        dom = {name: MagicMock(**{"state.return_value": [state, 0], "isActive.return_value": active})
               for name, state, active in (("running", 1, 1), ("crashed", 6, 1), ("off", 5, 0))}
        for kind, found, state in ((StartVM, "running", Operation.SUCCEEDED), (StartVM, "crashed", Operation.FAILED),
                                   (StartVM, "off", Operation.FAILED), (StartVM, None, Operation.FAILED),
                                   (ForceOffVM, "off", Operation.SUCCEEDED), (ForceOffVM, "running", Operation.FAILED),
                                   (ForceOffVM, None, Operation.SUCCEEDED),  # a transient VM is removed as it stops
                                   (ShutdownVM, "off", Operation.SUCCEEDED), (ShutdownVM, None, Operation.SUCCEEDED),
                                   (ShutdownVM, "running", Operation.FAILED)):
            with self.subTest(kind=kind.name, found=found), patch("instances.jobs._domain", return_value=dom.get(found)):
                self.assertEqual(kind().reconcile(op).state, state)
        with patch("instances.jobs._domain", return_value=dom["running"]):  # its guest may yet shut it down
            self.assertIn("may still shut it down", ShutdownVM().reconcile(op).error[0]["text"])

    def test_a_refused_job_frees_its_vm(self):
        # through the worker: the job fails and its claims go, so the VM can be powered again
        from operations.worker import execute

        self.proxies["bp-vm1"].get_status.return_value = 5
        self.submit("force_off", self.vms[:1])
        op = Operation.objects.get()
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        execute(SimpleNamespace(identity="wvc-test:1:a", recovery=MagicMock()), op.pk)
        op.refresh_from_db()
        self.assertEqual((op.state, Claim.objects.filter(operation=op).count()), (Operation.FAILED, 0))

    def test_the_jobs_page_follows_an_owners_power_jobs(self):
        # an owner is sent to ?kind=...: the page filters it for them too
        owner = get_user_model().objects.create_user("bp-owner4", password="pw")
        UserInstance.objects.create(instance=self.vms[0], user=owner)
        response, _said = self.submit("start", self.vms[:1], user=owner)
        Operation.objects.create(kind="instance.snapshot", user=owner, username="bp-owner4", state=Operation.SUCCEEDED,
                                 resource="y", resource_label="bp-host/bp-vm1")
        page = self.client.get(response.url)
        self.assertEqual([op.kind for op, _data in page.context["rows"]], ["instance.start"])

    def test_a_template_is_not_started_and_nothing_is_uncertain(self):
        # refused before libvirt is asked: the job fails (its claims go), recovery is not needed
        Instance.objects.filter(pk=self.vms[0].pk).update(is_template=True)
        self.submit("start", self.vms[:1])
        op = Operation.objects.get()
        with self.assertRaisesRegex(OperationError, "Templates cannot be started"):
            self.run_job(op)
        op.refresh_from_db()
        self.assertNotIn("powering", op.intent)
        self.assertEqual(StartVM().reconcile(op).state, Operation.FAILED)
        self.proxies["bp-vm1"].start.assert_not_called()

    def test_a_vm_paused_by_an_administrator_or_gone_is_refused_when_the_job_runs(self):
        owner = get_user_model().objects.create_user("bp-owner3", password="pw")
        UserInstance.objects.create(instance=self.vms[0], user=owner)
        self.submit("start", self.vms[:1], user=owner)  # the request reads no VM state
        op = Operation.objects.get()
        self.proxies["bp-vm1"].get_status.return_value = 3  # paused
        with self.assertRaises(PermissionDenied):
            self.run_job(op)
        Instance.objects.filter(pk=self.vms[0].pk).delete()
        with self.assertRaises(PermissionDenied):
            StartVM().precheck(op, None)

    def test_the_worker_checks_the_user_again(self):
        # disabled after the form was sent: the job powers nothing
        owner = get_user_model().objects.create_user("bp-owner2", password="pw")
        UserInstance.objects.create(instance=self.vms[0], user=owner)
        self.submit("start", self.vms[:1], user=owner)
        get_user_model().objects.filter(pk=owner.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.run_job(Operation.objects.get())
        self.proxies["bp-vm1"].start.assert_not_called()

    def test_an_owner_powers_only_their_own_vms(self):
        owner = get_user_model().objects.create_user("bp-owner", password="pw")
        UserInstance.objects.create(instance=self.vms[0], user=owner)
        _response, said = self.submit("start", self.vms, user=owner)
        # another's VM is not named: the owner may not see it
        self.assertEqual(said, ["a chosen VM: you may not power it now", "1 VM is queued; the Jobs page follows it."])
        self.assertEqual(Operation.objects.get().params["instance"], self.vms[0].pk)

    def test_an_auditor_is_refused_by_the_name_of_a_vm_they_see(self):
        auditor = get_user_model().objects.create_user("bp-auditor", password="pw")
        auditor.user_permissions.add(Permission.objects.get(codename="view_instances"))
        _response, said = self.submit("start", self.vms[:1], user=auditor)
        self.assertEqual(said, ["bp-vm1: you may not power it now"])
        self.assertFalse(Operation.objects.exists())

    def test_a_refusal_goes_back_to_the_list_it_came_from(self):
        host_list = reverse("instances", args=[self.vms[0].compute_id])
        for given, back in ((host_list, host_list), ("?page=2", reverse("instances:index")), ("//example.com/", reverse("instances:index")),
                             ("https://example.com/", reverse("instances:index"))):
            response = self.client.post(reverse("instances:bulk_power"), {"action": "reboot", "vm": [self.vms[0].pk],
                                                                           "submission_key": "key-bulkpow1", "next": given})
            self.assertRedirects(response, back, fetch_redirect_response=False)

    def test_a_host_s_instances_page_has_the_vm_list_and_its_bar(self):
        host_list = reverse("instances", args=[self.vms[0].compute_id])
        with patch("computes.views.vm_states", return_value={}), \
                patch("computes.views.utils.refresh_instance_database"), patch("computes.views.read_list_rows"):
            page = html.fromstring(self.client.get(host_list).content)
        self.assertEqual(sorted(int(box.get("value")) for box in page.xpath("//input[@name='vm']")), [vm.pk for vm in self.vms])
        (form,) = page.xpath("//form[@id='bulk-power']")
        self.assertEqual(form.xpath(".//input[@name='next']/@value"), [host_list])
        self.assertTrue(page.xpath("//*[@id='state-pills']"))
        self.assertNotIn("Host", page.xpath("//thead//th/text()"))  # one host: no host column

    def test_an_unknown_action_or_too_many_vms_is_refused(self):
        self.submit("reboot", self.vms)
        response = self.client.post(reverse("instances:bulk_power"), {"action": "start", "vm": [str(n) for n in range(1, 502)],
                                                                       "submission_key": "key-bulkpow1"})
        self.assertIn("at most 500 VMs", " ".join(map(str, get_messages(response.wsgi_request))))
        self.assertFalse(Operation.objects.exists())

    def test_the_list_offers_a_box_for_each_vm_and_the_actions(self):
        with patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.refresh_instance_database"), patch("instances.views.utils.read_list_rows"):
            page = html.fromstring(self.client.get(reverse("instances:index")).content)
        boxes = page.xpath("//input[@type='checkbox'][@name='vm']")
        self.assertEqual(sorted(int(box.get("value")) for box in boxes), [vm.pk for vm in self.vms])
        (form,) = page.xpath("//form[@id='bulk-power']")
        self.assertEqual(form.get("action"), reverse("instances:bulk_power"))
        self.assertEqual(form.xpath(".//button[@name='action'][not(@formaction)]/@value"), ["start", "shutdown", "force_off"])
        # a bar shown while VMs are chosen; the table's head chooses those shown
        self.assertIsNotNone(form.get("hidden"))
        self.assertTrue(page.xpath("//thead//input[@id='bulk-power-shown']"))
        # an owner: a box on their own VM only
        owner = get_user_model().objects.create_user("bp-lister", password="pw")
        UserInstance.objects.create(instance=self.vms[1], user=owner)
        self.client.force_login(owner)
        with patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.refresh_instance_database"), patch("instances.views.utils.read_list_rows"):
            page = html.fromstring(self.client.get(reverse("instances:index")).content)
        self.assertEqual([int(box.get("value")) for box in page.xpath("//input[@name='vm']")], [self.vms[1].pk])
