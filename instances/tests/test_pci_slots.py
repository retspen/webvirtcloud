"""A running q35 VM gives each PCIe device (a virtio disk, a NIC) a root port
of its own and gets no new one: a new VM has spare ports, as virt-install
makes them, and a refusal for want of one says what to do instead. A new
volume whose attach fails stays in its pool: it is never deleted unasked."""

from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from instances.models import Instance
from logs.models import Logs
from libvirt import libvirtError
from lxml import etree
from vrtManager.create import PCIE_ROOT_PORTS, wvmCreate

DOM_CAPS = {"domain": "kvm", "os_support": "no", "cpu_modes": ["host-model"], "cpu_custom_models": [],
            "disk_bus": ["virtio", "sata", "scsi"]}
NO_SLOT = libvirtError("internal error: No more available PCI slots")


def defined_controllers(machine):
    conn = wvmCreate.__new__(wvmCreate)
    conn.wvm = MagicMock()
    with patch.object(wvmCreate, "get_capabilities", return_value={"features": []}), \
            patch.object(wvmCreate, "get_dom_capabilities", return_value=DOM_CAPS):
        conn.create_instance(name="vm-1", memory=512, vcpu=1, vcpu_mode="host-model",
                             uuid="00000000-0000-4000-8000-0000000000c2", arch="x86_64", machine=machine,
                             firmware={}, volumes=[], networks="default", nwfilter="", virtio=True,
                             listener_addr="0.0.0.0", add_cdrom="None", add_input="None")
    domain = etree.fromstring(conn.wvm.defineXML.call_args.args[0])
    return [c.get("model") for c in domain.findall("devices/controller[@type='pci']")]


class NewVmPortsTests(SimpleTestCase):
    def test_a_new_q35_vm_has_spare_root_ports(self):
        # libvirt puts the VM's devices into these and adds none: the rest are free
        self.assertEqual(defined_controllers("pc-q35-rhel9.8.0"), ["pcie-root"] + ["pcie-root-port"] * PCIE_ROOT_PORTS)

    def test_a_pc_vm_has_none_its_pci_bus_has_slots(self):
        self.assertEqual(defined_controllers("pc-i440fx-rhel7.6.0"), [])


class NoPciSlotTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("ps-admin", "ps@example.com", "x"))
        compute = Compute.objects.create(name="ps", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="ps-vm",
                                                uuid="aaaaaaaa-7777-2222-3333-444444444444")

    def post(self, view, data, error):
        with patch("instances.models.wvmInstance") as wvm, patch("instances.views.wvmStorage") as storage, \
                patch("instances.views.wvmCreate") as create:
            proxy = wvm.return_value
            proxy.get_disk_devices.return_value = proxy.get_media_devices.return_value = []
            proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            proxy.get_cache_modes.return_value = {"default": ""}
            proxy.get_status.return_value = 1
            proxy.attach_disk.side_effect = proxy.add_network.side_effect = error
            storage.return_value.get_volumes.return_value = ["data.qcow2"]
            storage.return_value.get_type.return_value = "dir"
            storage.return_value.get_volume_type.return_value = "file"
            storage.return_value.get_volume_format_type.return_value = "qcow2"
            create.return_value.create_volume.return_value = "/pool/data.qcow2"
            response = self.client.post(reverse(f"instances:{view}", args=[self.instance.id]), data,
                                        HTTP_REFERER=reverse("instances:instance", args=[self.instance.id]))
        return [str(m) for m in get_messages(response.wsgi_request)], storage.return_value.del_volume

    def test_a_new_disk_without_a_slot_is_told_the_scsi_bus_and_its_volume_stays(self):
        texts, del_volume = self.post("add_new_vol", {"storage": "default", "name": "data", "format": "qcow2",
                                                      "size": "1", "cache": "default", "bus": "virtio"}, NO_SLOT)
        self.assertEqual(len(texts), 1)
        self.assertIn("choose the scsi bus", texts[0])
        del_volume.assert_not_called()
        # the refusal is logged as failed
        self.assertFalse(Logs.objects.get(instance=self.instance.name).success)

    def test_a_scsi_disk_without_a_slot_for_its_controller_is_told_to_shut_the_vm_down(self):
        texts, _del_volume = self.post("add_new_vol", {"storage": "default", "name": "data", "format": "qcow2",
                                                       "size": "1", "cache": "default", "bus": "scsi"}, NO_SLOT)
        self.assertEqual(len(texts), 1)
        self.assertIn("the SCSI controller the disk needs", texts[0])
        self.assertNotIn("choose the scsi bus", texts[0])

    def test_another_refusal_is_libvirts(self):
        texts, del_volume = self.post("add_new_vol", {"storage": "default", "name": "data", "format": "qcow2",
                                                      "size": "1", "cache": "default", "bus": "virtio"},
                                      libvirtError("internal error: something else"))
        self.assertEqual(texts, ["libvirt Error - internal error: something else"])
        del_volume.assert_not_called()

    def test_an_existing_volume_without_a_slot_is_told_the_scsi_bus_and_stays(self):
        texts, del_volume = self.post("add_existing_vol", {"selected_storage": "default", "vols": "data.qcow2",
                                                           "cache": "default", "bus": "virtio"}, NO_SLOT)
        self.assertIn("choose the scsi bus", texts[0])
        del_volume.assert_not_called()

    def test_a_network_device_without_a_slot_is_told_to_shut_the_vm_down(self):
        texts, _del_volume = self.post("add_network", {"add-net-network": "net:default", "add-net-model": "virtio"},
                                       NO_SLOT)
        self.assertEqual(len(texts), 1)
        self.assertIn("shut it down", texts[0])
