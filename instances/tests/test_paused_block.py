"""A VM an administrator paused stays paused until an administrator resumes
it: its owners cannot power it off or cycle it, on the page or the API."""

from unittest.mock import patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import VIR_DOMAIN_PAUSED, VIR_DOMAIN_RUNNING


class PausedBlockTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("pb-owner", password="pw")
        self.admin = User.objects.create_superuser("pb-admin", "pb@example.com", "pw")
        compute = Compute.objects.create(name="pb", hostname="192.0.2.1", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="pb-vm", uuid="14141414-0000-0000-0000-000000000000")
        UserInstance.objects.create(user=self.owner, instance=self.vm, is_change=True, is_delete=True)
        patcher = patch("instances.models.wvmInstance")
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)

    def test_an_owner_cannot_power_a_paused_vm(self):
        self.proxy.get_status.return_value = VIR_DOMAIN_PAUSED
        self.client.force_login(self.owner)
        for view in ("force_off", "powercycle", "poweroff", "poweron"):
            self.assertEqual(self.client.post(reverse(f"instances:{view}", args=[self.vm.pk])).status_code, 403, view)
        api = reverse("compute-instance-forceoff", kwargs={"compute_pk": self.vm.compute_id, "pk": self.vm.pk})
        self.assertEqual(self.client.post(api).status_code, 403)
        self.proxy.force_shutdown.assert_not_called()
        self.proxy.shutdown.assert_not_called()

    def test_an_administrator_can_and_an_owner_of_a_running_vm_can(self):
        self.proxy.get_status.return_value = VIR_DOMAIN_PAUSED
        self.client.force_login(self.admin)
        self.client.post(reverse("instances:force_off", args=[self.vm.pk]))
        self.proxy.get_status.return_value = VIR_DOMAIN_RUNNING
        self.client.force_login(self.owner)
        self.client.post(reverse("instances:force_off", args=[self.vm.pk]))
        self.assertEqual(self.proxy.force_shutdown.call_count, 2)
