"""A device form sent twice (a double click, a resent request) adds the
device once: libvirt takes the same disk file or MAC twice in the
persistent definition."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from instances.models import Instance

PATH = "/var/lib/libvirt/images/data.qcow2"
MAC = "52:54:00:aa:bb:cc"


class DuplicateDeviceTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("dup-admin", "d@example.com", "pw"))
        compute = Compute.objects.create(name="dup-c", hostname="192.0.2.40", login="root", password="", type=1)
        self.vm = Instance.objects.create(compute=compute, name="dup-vm", uuid="12121212-0000-1111-2222-333333333333")
        self.proxy = MagicMock()
        self.proxy.get_disk_devices.return_value = []
        self.proxy.get_media_devices.return_value = []
        self.proxy.get_net_devices.return_value = []
        self.proxy.get_disk_bus_types.return_value = ["virtio"]
        self.proxy.get_cache_modes.return_value = {"default": "Default"}
        patcher = patch("instances.models.wvmInstance", return_value=self.proxy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, name, data):
        response = self.client.post(reverse(f"instances:{name}", args=[self.vm.pk]), data)
        return [str(m) for m in get_messages(response.wsgi_request)]

    @patch("instances.views.wvmStorage")
    def test_a_disk_of_the_vm_is_not_attached_again(self, storage):
        pool = storage.return_value
        pool.get_volumes.return_value = ["data.qcow2"]
        pool.get_type.return_value = "dir"
        pool.get_volume_format_type.return_value = "qcow2"
        pool.get_volume_type.return_value = "file"
        pool.get_volume.return_value.path.return_value = PATH
        form = {"selected_storage": "default", "vols": "data.qcow2", "bus": "virtio", "cache": "default"}
        self.post("add_existing_vol", form)
        self.proxy.attach_disk.assert_called_once()
        # the first attach is in the persistent definition only (a shut-off VM)
        self.proxy.get_disk_devices.side_effect = lambda config=False: [{"path": PATH, "dev": "vdb"}] if config else []
        self.assertEqual(self.post("add_existing_vol", form), ["data.qcow2 is already a disk of this VM"])
        self.proxy.attach_disk.assert_called_once()

    def test_a_nic_with_the_mac_of_another_is_not_added(self):
        form = {"add-net-network": "net:default", "add-net-mac": MAC, "add-net-model": "virtio"}
        self.post("add_network", form)
        self.proxy.add_network.assert_called_once()
        self.proxy.get_net_devices.side_effect = lambda config=False: [{"mac": MAC}] if config else []
        form["add-net-mac"] = MAC.upper()
        self.assertEqual(self.post("add_network", form),
                         [f"The VM already has a network device with MAC {MAC.upper()}"])
        self.proxy.add_network.assert_called_once()
