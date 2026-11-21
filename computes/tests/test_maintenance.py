"""A host in maintenance takes no new VM and no migration, and Balance leaves
it out; its VMs run on. A superuser puts it in maintenance and takes it out
on its page, each change audited."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from accounts.models import UserInstance
from computes.jobs import Balance
from computes.models import Compute
from computes.tests.test_balance import Ctx
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from instances.jobs import CloneInstance, CreateInstance, RevertSnapshot, _finish_clone, _revert_start, migration_target
from instances.models import Instance
from libvirt import libvirtError
from logs.models import Logs
from operations.jobs import SUBMISSION_KEY_TTL
from operations.models import Claim, Operation
from vrtManager import util

REFUSED = "is in maintenance: no new VM or migration comes to it"


class MaintenanceSwitchTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="mt", hostname="192.0.2.61", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("mt-admin", "mt@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row

    def switch(self, state):
        return self.client.post(reverse("compute_maintenance", args=[self.compute.pk]), {"maintenance": state})

    def test_the_form_sets_the_state_it_names_and_each_change_is_audited(self):
        self.assertRedirects(self.switch("on"), reverse("overview", args=[self.compute.pk]), fetch_redirect_response=False)
        self.compute.refresh_from_db()
        since = self.compute.maintenance_since
        self.switch("on")  # a second page sent meanwhile does not turn it back, nor starts it anew
        self.compute.refresh_from_db()
        self.assertEqual(self.compute.maintenance_since, since)
        self.switch("off")
        self.compute.refresh_from_db()
        self.assertFalse(self.compute.maintenance)
        self.assertEqual(list(Logs.objects.order_by("id").values_list("message", flat=True)),
                         ["Compute mt: maintenance on", "Compute mt: maintenance on", "Compute mt: maintenance off"])

    def test_only_a_post_changes_it(self):
        self.assertEqual(self.client.get(reverse("compute_maintenance", args=[self.compute.pk])).status_code, 405)

    def test_a_vm_cannot_be_created_from_its_pages(self):
        self.compute.maintenance_since = timezone.now()
        self.compute.save()
        host_vms = reverse("instances", args=[self.compute.pk])
        for url in (reverse("instances:create_instance_select_type", args=[self.compute.pk]),
                    reverse("instances:create_instance", args=[self.compute.pk, "x86_64", "q35"])):
            # back to the page it was asked from (the host's VM list), not every VM's
            response = self.client.get(url, HTTP_REFERER=f"http://testserver{host_vms}")
            self.assertEqual(response.url, f"http://testserver{host_vms}")
            response = self.client.get(url, follow=True)  # typed in: the host's VM list too
            self.assertRedirects(response, host_vms)
            self.assertContains(response, f"mt {REFUSED}")

    def test_the_host_vm_list_offers_no_new_vm(self):
        from lxml import html as lxml_html

        page = lambda: lxml_html.fromstring(self.client.get(reverse("instances", args=[self.compute.pk])).content)
        create = reverse("instances:create_instance_select_type", args=[self.compute.pk])
        self.assertTrue(page().xpath("//a[@href=$u]", u=create))
        self.compute.maintenance_since = timezone.now()
        self.compute.save()
        self.assertFalse(page().xpath("//a[@href=$u]", u=create))
        self.assertTrue(page().xpath("//button[@disabled][contains(., 'New VM')]"))


class MaintenanceGuardTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("mg-admin", "mg@example.com", "pw")
        self.host = Compute.objects.create(name="mg", hostname="192.0.2.62", login="", password="", type=4,
                                           maintenance_since=timezone.now())
        self.other = Compute.objects.create(name="mg-other", hostname="192.0.2.63", login="", password="", type=4)

    def test_no_vm_migrates_to_it(self):
        with self.assertRaisesRegex(util.OperationError, f"mg {REFUSED}"):
            migration_target(Instance(compute=self.other, name="vm"), self.host.pk)

    def test_no_vm_is_created_on_it_nor_by_a_job_queued_before(self):
        with self.assertRaisesRegex(util.OperationError, REFUSED):
            CreateInstance().validate(self.admin, {"compute": self.host.pk})
        with self.assertRaisesRegex(util.OperationError, REFUSED):
            CreateInstance().precheck(SimpleNamespace(user=self.admin, params={"compute": self.host.pk, "name": "new"}),
                                      None)

    def test_no_vm_is_cloned_on_it(self):
        with patch("instances.jobs._clonable", return_value=Instance(compute=self.host, name="vm")), \
                self.assertRaisesRegex(util.OperationError, REFUSED):
            CloneInstance().plan(self.admin, {"instance": 1, "fields": {}})


class BalanceLeavesItOutTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("mb-admin", "mb@example.com", "pw")
        self.hosts = [Compute.objects.create(name=f"mb-{n}", hostname=f"192.0.2.7{n}", login="", password="", type=4)
                      for n in range(2)]
        self.vm = Instance.objects.create(compute=self.hosts[0], name="mb-vm", uuid="00000000-0000-4000-8000-000000000201")
        self.params = {"parallel": 1, "moves": [[self.vm.pk, self.hosts[0].pk, self.hosts[1].pk]]}

    def maintenance(self, host):
        Compute.objects.filter(pk=host.pk).update(maintenance_since=timezone.now())

    def test_a_move_from_or_to_a_host_in_maintenance_is_refused(self):
        for host, text in ((self.hosts[0], "mb-0 is in maintenance: Balance leaves it out"),
                           (self.hosts[1], f"mb-1 {REFUSED}")):
            Compute.objects.update(maintenance_since=None)
            self.maintenance(host)
            with self.assertRaisesRegex(util.OperationError, text):
                Balance().validate(self.admin, Balance().normalize(self.params))

    def test_a_host_put_in_maintenance_after_the_job_was_asked_for_gives_no_vm(self):
        op = Operation.objects.create(kind="host.balance", user=self.admin, username=self.admin.username,
                                      submission_key="key-mb000001", params=self.params,
                                      intent=Balance().plan(self.admin, self.params).intent)
        self.maintenance(self.hosts[0])
        with self.assertRaisesRegex(util.OperationError, "mb-vm: mb-0 is in maintenance"):
            Balance().run(op, Ctx(op))
        self.assertFalse(Operation.objects.filter(kind="instance.migrate").exists())


class NoStartTests(TestCase):
    """None of the VMs of a host in maintenance starts there, also for its owner."""

    def setUp(self):
        self.compute = Compute.objects.create(name="ms", hostname="192.0.2.81", login="", password="", type=1,
                                              maintenance_since=timezone.now())
        self.instance = Instance.objects.create(compute=self.compute, name="ms-vm",
                                                uuid="00000000-0000-4000-8000-000000000301")
        self.client.force_login(get_user_model().objects.create_superuser("ms-admin", "ms@example.com", "pw"))
        self.proxy = MagicMock()
        patcher = patch.object(Instance, "proxy", new_callable=lambda: self.proxy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_vm_is_not_started_nor_resumed_nor_power_cycled(self):
        for action in ("poweron", "resume", "powercycle"):
            response = self.client.post(reverse(f"instances:{action}", args=[self.instance.pk]), follow=True)
            self.assertContains(response, "ms is in maintenance: its VMs cannot be started there")
            self.assertNotContains(response, "libvirt Error")  # the panel's own refusal
        self.proxy.start.assert_not_called()
        self.proxy.resume.assert_not_called()
        self.proxy.force_shutdown.assert_not_called()  # a power cycle would leave it off

    def test_no_revert_starts_a_shut_off_vm(self):
        self.proxy.get_status.return_value = 5
        for state, refused in (("running", True), ("paused", True), ("shutoff", False), ("disk-snapshot", False)):
            self.proxy._snapshot.return_value.getXMLDesc.return_value = (
                f"<domainsnapshot><state>{state}</state></domainsnapshot>")
            if refused:
                with self.assertRaisesRegex(util.OperationError, "its VMs cannot be started there"):
                    _revert_start(self.instance, self.proxy, {"name": "s", "external": False})
            else:
                _revert_start(self.instance, self.proxy, {"name": "s", "external": False})
        self.proxy.get_status.return_value = 3  # paused: a running snapshot resumes it
        self.proxy._snapshot.return_value.getXMLDesc.return_value = "<domainsnapshot><state>running</state></domainsnapshot>"
        with self.assertRaisesRegex(util.OperationError, "its VMs cannot be started there"):
            _revert_start(self.instance, self.proxy, {"name": "s", "external": False})
        self.proxy.get_status.return_value = 1  # running already: the revert starts nothing
        self.proxy._snapshot.return_value.getXMLDesc.return_value = "<domainsnapshot><state>running</state></domainsnapshot>"
        _revert_start(self.instance, self.proxy, {"name": "s", "external": False})

    def test_nor_by_its_owner(self):
        owner = get_user_model().objects.create_user("ms-owner", "owner@example.com", "pw")
        UserInstance.objects.create(instance=self.instance, user=owner)
        self.client.force_login(owner)
        response = self.client.post(reverse("instances:poweron", args=[self.instance.pk]), follow=True)
        self.assertContains(response, "ms is in maintenance: its VMs cannot be started there")
        self.proxy.start.assert_not_called()

    def test_a_revert_job_that_would_start_it_is_refused(self):
        self.proxy.get_status.return_value = 5
        self.proxy._snapshot.return_value.getXMLDesc.return_value = "<domainsnapshot><state>running</state></domainsnapshot>"
        admin = get_user_model().objects.get(username="ms-admin")
        with patch("instances.jobs._proxy", return_value=self.proxy), \
                self.assertRaisesRegex(util.OperationError, "its VMs cannot be started there"):
            RevertSnapshot().validate(admin, {"instance": self.instance.pk, "name": "s", "external": False})

    def test_its_autostart_cannot_be_turned_on(self):
        response = self.client.post(reverse("instances:set_autostart", args=[self.instance.pk]), follow=True)
        self.assertContains(response, "ms is in maintenance: its VMs cannot be started there")
        self.proxy.set_autostart.assert_not_called()

    def test_a_compute_read_before_the_maintenance_refuses_too(self):
        held = Compute.objects.get(pk=self.compute.pk)
        Compute.objects.filter(pk=held.pk).update(maintenance_since=None)
        held.refuse_start()  # out of maintenance now, though the object says otherwise
        Compute.objects.filter(pk=held.pk).update(maintenance_since=timezone.now())
        stale = Compute.objects.get(pk=held.pk)
        stale.maintenance_since = None  # as read before it went in maintenance
        with self.assertRaisesRegex(util.OperationError, "its VMs cannot be started there"):
            stale.refuse_start()
        with self.assertRaisesRegex(util.OperationError, REFUSED):
            stale.refuse_new_vms()

    def test_a_running_vm_still_stops(self):
        self.client.post(reverse("instances:poweroff", args=[self.instance.pk]))
        self.proxy.shutdown.assert_called_once()


class MaintenanceWithMigrationTests(TestCase):
    """"Put in maintenance" on a host with running VMs opens Bulk Migrate,
    which puts the host in maintenance with the job, or without migrating."""

    def setUp(self):
        self.compute = Compute.objects.create(name="me", hostname="192.0.2.91", login="", password="", type=4)
        self.other = Compute.objects.create(name="me-other", hostname="192.0.2.92", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=self.compute, name="me-vm", uuid="00000000-0000-4000-8000-000000000401")
        self.admin = get_user_model().objects.create_superuser("me-admin", "me@example.com", "pw")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()

    def post(self, key="mnt00000key", moves=True):
        return self.client.post(reverse("bulk_migrate", args=[self.compute.pk]), {
            "target": self.other.pk, "instance": [self.vm.pk] if moves else [], "parallel": "1",
            "maintenance": "on", "submission_key": key})

    def maintenance(self):
        self.compute.refresh_from_db()
        return self.compute.maintenance

    def test_the_host_goes_in_maintenance_with_the_job(self):
        self.assertRedirects(self.post(), reverse("instances", args=[self.compute.pk]), fetch_redirect_response=False)
        (op,) = Operation.objects.all()
        self.assertTrue(op.params["maintenance"])
        self.assertTrue(self.maintenance())
        self.assertEqual(self.compute.maintenance_since, op.created_at)  # the job is of this maintenance
        self.assertEqual(list(Logs.objects.values_list("message", flat=True)), ["Compute me: maintenance on"])

    def test_a_refused_job_leaves_the_host_out_of_maintenance(self):
        response = self.post(moves=False)
        self.assertRedirects(response, reverse("bulk_migrate", args=[self.compute.pk]) + f"?target={self.other.pk}"
                             "&maintenance=on", fetch_redirect_response=False)
        self.assertFalse(Operation.objects.exists())
        self.assertFalse(self.maintenance())

    def test_the_form_sent_after_its_key_expired_puts_it_back_with_its_new_job(self):
        self.post()
        Operation.objects.update(created_at=timezone.now() - SUBMISSION_KEY_TTL - timedelta(minutes=1),
                                 state=Operation.SUCCEEDED)
        Claim.objects.all().delete()  # it ended
        Compute.objects.filter(pk=self.compute.pk).update(maintenance_since=None)
        self.post()
        self.assertTrue(self.maintenance())
        self.assertEqual(Operation.objects.count(), 2)

    def test_the_form_sent_again_does_not_put_it_back(self):
        self.post()
        Compute.objects.filter(pk=self.compute.pk).update(maintenance_since=None)  # taken out since
        self.post()
        self.assertFalse(self.maintenance())
        self.assertEqual(Operation.objects.count(), 1)

    def page(self, **query):
        def read_list_rows(instances, computes):  # a running VM, without asking a host
            for instance in instances:
                instance.__dict__["info"] = [1, 131072, 131072, 1, 0]

        with patch("computes.views.utils.refresh_instance_database"), \
                patch("computes.views.read_list_rows", side_effect=read_list_rows), \
                patch("computes.reach.Reach.refusal", return_value=None):
            return self.client.get(reverse("bulk_migrate", args=[self.compute.pk]), query)

    def test_the_page_offers_both_ways_into_maintenance(self):
        response = self.page(maintenance="on")
        self.assertContains(response, "Put in maintenance without migrating")
        self.assertContains(response, '<input type="hidden" name="maintenance" value="on">', count=3)
        Compute.objects.filter(pk=self.compute.pk).update(maintenance_since=timezone.now())  # already: the plain page
        self.assertNotContains(self.page(maintenance="on"), "Put in maintenance without migrating")


class MaintenanceStateTests(TestCase):
    """A host in maintenance is ready once none of its VMs runs; until then,
    or while it cannot be read, its maintenance is only asked for."""

    def setUp(self):
        self.compute = Compute.objects.create(name="mz", hostname="192.0.2.95", login="", password="", type=4,
                                              maintenance_since=timezone.now())
        self.client.force_login(get_user_model().objects.create_superuser("mz-admin", "mz@example.com", "pw"))

    @staticmethod
    def given(**vms):
        return {"vms": {"running": 0, "paused": 0, "shutoff": 0, "other": 0, **vms}, "cpus": 1, "memory": 1,
                "vcpus": {"all": 0, "running": 0}, "assigned": {"all": 0, "running": 0}}

    def overview(self, given):
        with patch.object(Compute, "status", True), patch("computes.views.wvmHostDetails", side_effect=libvirtError("not read")), \
                patch.object(Compute, "capacity", given), patch("computes.views.host_pools"):
            return self.client.get(reverse("overview", args=[self.compute.pk]))

    def test_running_or_paused_vms_keep_it_requested(self):
        response = self.overview(self.given(running=1, paused=1, shutoff=3))
        self.assertContains(response, "Maintenance requested: 2 VMs still run on this host.")
        self.assertNotContains(response, "In maintenance: no VM runs")

    def test_with_only_shut_off_vms_it_is_in_maintenance(self):
        self.assertContains(self.overview(self.given(shutoff=3)), "In maintenance: no VM runs on this host.")

    def test_the_vms_that_autostart_when_the_host_boots_are_named(self):
        doms = [MagicMock(**{"name.return_value": name, "autostart.return_value": on})
                for name, on in (("mz-b", 1), ("mz-off", 0), ("mz-a", 1))]
        proxy = MagicMock(**{"wvm.listAllDomains.return_value": doms})
        with patch.object(Compute, "proxy", new_callable=lambda: proxy):
            response = self.overview(self.given(shutoff=3))
        self.assertContains(response, "These VMs start by themselves when the host boots: mz-a, mz-b.")

    def test_a_host_that_cannot_be_read_is_not_said_ready(self):
        self.assertContains(self.overview(None), "whether its VMs still run is not known")

    def bulk(self, state, before):
        op = Operation.objects.create(kind="host.bulk_migrate", user=None, username="mz-admin", state=state,
                                      resource=f"compute:{self.compute.pk}")
        if before:
            Operation.objects.filter(pk=op.pk).update(created_at=self.compute.maintenance_since - timedelta(hours=1))
        return op

    def test_only_a_bulk_migration_of_this_maintenance_or_one_still_running_is_shown(self):
        self.bulk(Operation.SUCCEEDED, before=True)  # an earlier one
        response = self.overview(self.given(running=1))
        self.assertNotContains(response, "bulk migration")
        self.assertNotContains(response, "being migrated")
        running = self.bulk(Operation.RUNNING, before=True)
        self.assertContains(self.overview(self.given(running=1)), "Its VMs are being migrated")
        Operation.objects.filter(pk=running.pk).update(state=Operation.FAILED)
        self.bulk(Operation.FAILED, before=False)
        self.assertContains(self.overview(self.given(running=1)), "Its last bulk migration")

    def test_put_in_maintenance_leads_to_bulk_migrate_while_vms_run(self):
        Compute.objects.filter(pk=self.compute.pk).update(maintenance_since=None)
        response = self.overview(self.given(running=1))
        self.assertContains(response, reverse("bulk_migrate", args=[self.compute.pk]) + "?maintenance=on")
        response = self.overview(self.given(shutoff=1))
        self.assertContains(response, reverse("compute_maintenance", args=[self.compute.pk]))


class CloneStaysOffTests(TestCase):
    def test_a_clone_made_while_the_host_went_in_maintenance_stays_off(self):
        compute = Compute.objects.create(name="mc", hostname="192.0.2.97", login="", password="", type=1,
                                         maintenance_since=timezone.now())
        op = SimpleNamespace(intent={"compute": compute.pk, "name": "mc-clone",
                                     "uuid": "00000000-0000-4000-8000-000000000501"},
                             username="mc-admin", client_ip=None)
        with patch("instances.jobs.wvmInstance") as proxy:
            result = _finish_clone(op, {"start": True}, "")
        proxy.return_value.start.assert_not_called()
        self.assertIn("is in maintenance: its VMs cannot be started there", str(result["warning"]))


class MaintenanceSinceMigrationTests(TransactionTestCase):
    """A host in maintenance before maintenance_since stays in maintenance."""

    def test_a_host_in_maintenance_stays_in_it(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("computes", "0010_maintenance")])
        old = executor.loader.project_state([("computes", "0010_maintenance")]).apps.get_model("computes", "Compute")
        old.objects.create(name="mm-on", hostname="192.0.2.97", login="", password="", type=4, maintenance=True)
        old.objects.create(name="mm-off", hostname="192.0.2.98", login="", password="", type=4)
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual({c.name: c.maintenance for c in Compute.objects.all()}, {"mm-on": True, "mm-off": False})
