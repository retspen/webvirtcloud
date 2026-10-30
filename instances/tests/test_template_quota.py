"""Templates do not count towards the quota and cannot be started. Turning a
template back into a VM adds it to its owner's usage, so for users with a
quota it is checked like any other increase. Only a shut-off VM changes."""

from unittest.mock import patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from instances.utils import QUOTA_UNVERIFIED


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
        _, messages = self.post(self.staff, is_template=False, quota="cpu")
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
        check, _ = self.post(admin, is_template=False, quota="cpu")
        self.assertFalse(self.vm.is_template)
        check.assert_not_called()
