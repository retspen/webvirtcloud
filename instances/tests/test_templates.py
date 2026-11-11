"""Templates: only superusers and staff mark or unmark one; a template is
not started, does not count towards the quota (turning it back into a VM
is checked), and is changed or deleted only by superusers and staff owners."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance
from operations.models import Operation
from logs.models import Logs
from django.contrib.messages import get_messages
from instances.utils import QUOTA_UNVERIFIED, QuotaExceeded


class TemplateRulesTestCase(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="tpl-c", hostname="192.0.2.5", login="root", password="", type=1)
        self.template = Instance.objects.create(
            compute=compute, name="tpl-vm", uuid="ffffffff-0000-1111-2222-333333333333", is_template=True
        )
        self.owner = get_user_model().objects.create_user("tpl_owner", password="x")
        UserInstance.objects.create(instance=self.template, user=self.owner, is_delete=True)
        self.staff = get_user_model().objects.create_user("tpl_staff", password="x", is_staff=True)
        UserInstance.objects.create(instance=self.template, user=self.staff, is_delete=True)

    def test_power_cycle_does_not_start_a_template(self):
        api = APIClient()
        api.force_login(self.owner)
        self.client.force_login(self.owner)
        for post in (
            lambda: self.client.post(reverse("instances:powercycle", args=[self.template.id])),
            lambda: api.post(reverse("compute-instance-powercycle", args=[self.template.compute_id, self.template.id])),
        ):
            with patch("instances.models.wvmInstance") as wvm:
                post()
            self.assertFalse(wvm.return_value.start.called)
            self.assertFalse(wvm.return_value.force_shutdown.called)

    def test_only_staff_owners_delete_a_template(self):
        self.client.force_login(self.owner)
        with patch("instances.models.wvmInstance") as wvm:
            response = self.client.post(reverse("instances:destroy", args=[self.template.id]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(wvm.return_value.delete.called)

        self.client.force_login(self.staff)
        with patch("instances.models.wvmInstance"):
            self.client.post(reverse("instances:destroy", args=[self.template.id]), {"submission_key": "key-tpldel01"})
        self.assertTrue(Operation.objects.filter(kind="instance.delete").exists())  # queued

    def test_the_destroy_confirmation_page_offers_the_form_to_who_may_delete(self):
        url = reverse("instances:destroy", args=[self.template.id])
        superuser = get_user_model().objects.create_superuser("tpl_root", "r@example.com", "x")
        for user, status, form in ((superuser, 200, True), (self.staff, 200, True), (self.owner, 403, False)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                with patch("instances.models.wvmInstance") as wvm:
                    wvm.return_value.get_status.return_value = 5
                    response = self.client.get(url)
                self.assertEqual(response.status_code, status)
                self.assertEqual('id="delete_form"' in response.content.decode(), form)


class TemplateFlagTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="tpl_super", email="tpl_super@example.com", password="x"
        )
        self.owner = User.objects.create_user(username="tpl_owner", password="x")
        self.staff_owner = User.objects.create_user(
            username="tpl_staff_owner", password="x", is_staff=True
        )
        self.compute = Compute.objects.create(
            name="tpl-compute", hostname="127.0.0.1:1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="tpl-vm",
            uuid="dddddddd-eeee-ffff-0000-111111111111",
        )
        for user in (self.owner, self.staff_owner):
            UserInstance.objects.create(instance=self.instance, user=user, is_change=True)

    def _post(self, user, action, data, status=302, autostart=0):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 5
            # unmarking a template checks the owner's quota with the VM's size
            wvm.return_value.get_vcpu.return_value = 1
            wvm.return_value.get_memory.return_value = 1024
            wvm.return_value.get_disk_devices.return_value = []
            wvm.return_value.get_autostart.return_value = autostart
            res = self.client.post(reverse(f"instances:{action}", args=[self.instance.id]), data)
        self.assertEqual(res.status_code, status)
        self.instance.refresh_from_db()
        return wvm.return_value

    def _make_template(self):
        self.instance.is_template = True
        self.instance.save(update_fields=["is_template"])

    def test_owner_cannot_mark_vm_as_template(self):
        self._post(self.owner, "set_template", {"is_template": "True"}, status=403)
        self.assertFalse(self.instance.is_template)

    def test_owner_cannot_change_a_template(self):
        # a template is changed only by superusers and staff owners
        self._make_template()
        self._post(self.owner, "change_options", {"title": "new title", "description": ""}, status=403)
        self.assertTrue(self.instance.is_template)

    def test_staff_owner_can_mark_and_unmark_template(self):
        self._post(self.staff_owner, "set_template", {"is_template": "True"})
        self.assertTrue(self.instance.is_template)
        # an unchecked switch is not submitted: "not a template"
        self._post(self.staff_owner, "set_template", {})
        self.assertFalse(self.instance.is_template)
        self.assertEqual(list(Logs.objects.filter(message__startswith="VM").order_by("id").values_list("message", "success")),
                         [("VM tpl-vm: mark as template", True), ("VM tpl-vm: unmark as template", True)])

    def test_a_template_does_not_start_with_the_host(self):
        proxy = self._post(self.superuser, "set_template", {"is_template": "True"}, autostart=1)
        self.assertTrue(self.instance.is_template)
        proxy.set_autostart.assert_called_once_with(0)
        proxy = self._post(self.superuser, "set_autostart", {})
        proxy.set_autostart.assert_not_called()

    def test_superuser_can_unmark_template(self):
        self._make_template()
        self._post(self.superuser, "set_template", {})
        self.assertFalse(self.instance.is_template)

    def test_the_title_form_leaves_the_template_alone(self):
        self._make_template()
        self._post(self.superuser, "change_options", {"title": "t", "description": ""})
        self.assertTrue(self.instance.is_template)


class TemplateFlagQuotaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user("tq-staff", password="pw", is_staff=True)
        compute = Compute.objects.create(name="tq", hostname="10.0.0.5", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="tq-vm", uuid="12345678-0000-0000-0000-00000000aaaa")
        UserInstance.objects.create(user=self.staff, instance=self.vm, is_change=True)

    def post(self, user, is_template, quota="", status=5):
        self.client.force_login(user)
        data = {"is_template": "on"} if is_template else {}
        with patch("instances.models.wvmInstance") as wvm, patch(
            "instances.views.utils.check_user_quota", return_value=quota
        ) as check:
            wvm.return_value.get_status.return_value = status
            wvm.return_value.get_vcpu.return_value = 2
            wvm.return_value.get_memory.return_value = 2048
            wvm.return_value.get_disk_devices.return_value = [{"size": 10 << 30}]
            response = self.client.post(reverse("instances:set_template", args=[self.vm.id]), data)
        self.vm.refresh_from_db()
        return check, [str(m) for m in get_messages(response.wsgi_request)]

    def test_making_a_template_needs_no_quota(self):
        check, _ = self.post(self.staff, is_template=True)
        self.assertTrue(self.vm.is_template)
        check.assert_not_called()

    def test_turning_a_template_into_a_vm_is_checked(self):
        Instance.objects.filter(pk=self.vm.pk).update(is_template=True)
        check, _ = self.post(self.staff, is_template=False)
        self.assertFalse(self.vm.is_template)
        check.assert_called_once_with(self.staff, 1, 2, 2048, 10)

    def test_over_quota_the_template_stays_a_template(self):
        Instance.objects.filter(pk=self.vm.pk).update(is_template=True)
        _, messages = self.post(self.staff, is_template=False, quota=QuotaExceeded("cpu", 9, 8))
        self.assertTrue(self.vm.is_template)
        self.assertTrue(any("quota" in m for m in messages), messages)

    def test_an_unverifiable_quota_keeps_it_a_template(self):
        Instance.objects.filter(pk=self.vm.pk).update(is_template=True)
        _, messages = self.post(self.staff, is_template=False, quota=QUOTA_UNVERIFIED)
        self.assertTrue(self.vm.is_template)
        self.assertTrue(any("cannot be reached" in m for m in messages), messages)

    def test_a_vm_that_is_not_shut_off_stays_as_it_is(self):
        # a running VM made a template would leave the quota while it runs
        for status in (1, 3):
            with self.subTest(status=status):
                check, messages = self.post(self.staff, is_template=True, status=status)
                self.assertFalse(self.vm.is_template)
                self.assertIn("Shut the VM down to change whether it is a template.", messages)

    def test_superusers_have_no_quota(self):
        Instance.objects.filter(pk=self.vm.pk).update(is_template=True)
        admin = get_user_model().objects.create_superuser("tq-admin", "tq@example.com", "pw")
        check, _ = self.post(admin, is_template=False, quota=QuotaExceeded("cpu", 9, 8))
        self.assertFalse(self.vm.is_template)
        check.assert_not_called()
