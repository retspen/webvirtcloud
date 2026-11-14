"""A clone copies the disks of the VM's persistent definition: its quota and
disk names come from those, not from the running VM's disks."""
from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from appsettings.models import AppSettings
from computes.models import Compute
from instances.models import Instance
from operations.models import Operation

LIVE = [{"dev": "vda", "path": "/pool/live.qcow2", "storage": "pool", "image": "live.qcow2", "size": 1 << 30}]
SAVED = [{"dev": "vdb", "path": "/pool/saved.qcow2", "storage": "pool", "image": "saved.qcow2", "size": 20 << 30}]


class CloneDisksTestCase(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="cd", hostname="192.0.2.5", login="root", password="", type=1)
        self.vm = Instance.objects.create(compute=compute, name="cd-vm", uuid="12345678-aaaa-bbbb-cccc-1234567890ab")

    def clone(self, user, **post):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ), patch("instances.views.utils.check_user_quota", return_value="") as quota:
            wvm.return_value.get_disk_devices.side_effect = lambda config=False: SAVED if config else LIVE
            wvm.return_value.get_vcpu.return_value = 1
            wvm.return_value.get_memory.return_value = 512
            wvm.return_value.get_net_devices.return_value = []
            wvm.return_value.get_status.return_value = 5
            response = self.client.post(reverse("instances:clone", args=[self.vm.id]), {"submission_key": "key-clone-disk1", **post})
            self.messages = [str(m) for m in response.wsgi_request._messages]
        return quota

    def test_the_quota_counts_the_disks_the_clone_copies(self):
        owner = get_user_model().objects.create_user("cd_owner", password="x")
        owner.user_permissions.add(Permission.objects.get(codename="clone_instances"))
        UserInstance.objects.create(instance=self.vm, user=owner, is_change=True)
        quota = self.clone(owner, name="cd-clone")
        self.assertEqual(quota.call_args.args[4], 20)

    def test_automatic_disk_names_are_for_the_disks_the_clone_copies(self):
        admin = get_user_model().objects.create_superuser("cd_admin", "cd@example.com", "x")
        AppSettings.objects.filter(key="CLONE_INSTANCE_AUTO_NAME").update(value="True")
        with patch("instances.views.utils.get_clone_free_names", return_value=["auto-1"]), patch(
            "instances.views.utils.get_dhcp_mac_address", return_value="52:54:00:00:00:01"
        ):
            self.clone(admin)
        data = Operation.objects.get().intent["clone"]
        self.assertIn("disk-vdb", data)
        self.assertNotIn("disk-vda", data)
