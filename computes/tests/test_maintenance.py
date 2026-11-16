"""A host in maintenance takes no new VM and no migration, and Balance leaves
it out; its VMs run on. A superuser puts it in maintenance and takes it out
on its page, each change audited."""

from types import SimpleNamespace
from unittest.mock import patch

from computes.jobs import Balance
from computes.models import Compute
from computes.tests.test_balance import Ctx
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.jobs import CloneInstance, CreateInstance, migration_target
from instances.models import Instance
from logs.models import Logs
from operations.models import Operation
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
        self.switch("on")  # a second page sent meanwhile does not turn it back
        self.compute.refresh_from_db()
        self.assertTrue(self.compute.maintenance)
        self.switch("off")
        self.compute.refresh_from_db()
        self.assertFalse(self.compute.maintenance)
        self.assertEqual(list(Logs.objects.order_by("id").values_list("message", flat=True)),
                         ["Compute mt: maintenance on", "Compute mt: maintenance on", "Compute mt: maintenance off"])

    def test_only_a_post_changes_it(self):
        self.assertEqual(self.client.get(reverse("compute_maintenance", args=[self.compute.pk])).status_code, 405)

    def test_a_vm_cannot_be_created_from_its_pages(self):
        self.compute.maintenance = True
        self.compute.save()
        for url in (reverse("instances:create_instance_select_type", args=[self.compute.pk]),
                    reverse("instances:create_instance", args=[self.compute.pk, "x86_64", "q35"])):
            response = self.client.get(url, follow=True)
            self.assertRedirects(response, reverse("instances:index"))
            self.assertContains(response, f"mt {REFUSED}")


class MaintenanceGuardTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("mg-admin", "mg@example.com", "pw")
        self.host = Compute.objects.create(name="mg", hostname="192.0.2.62", login="", password="", type=4,
                                           maintenance=True)
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
        Compute.objects.filter(pk=host.pk).update(maintenance=True)

    def test_a_move_from_or_to_a_host_in_maintenance_is_refused(self):
        for host, text in ((self.hosts[0], "mb-0 is in maintenance: Balance leaves it out"),
                           (self.hosts[1], f"mb-1 {REFUSED}")):
            Compute.objects.update(maintenance=False)
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
