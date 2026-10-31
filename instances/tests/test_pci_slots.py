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


DOMAIN = """<domain><devices>
<controller type='pci' index='0' model='pcie-root'/>
<controller type='pci' index='1' model='pcie-root-port'><address type='pci' bus='0x00' slot='0x02'/></controller>
<controller type='pci' index='2' model='pcie-root-port'><address type='pci' bus='0x00' slot='0x02' function='0x1'/></controller>
<controller type='pci' index='3' model='pcie-root-port'><address type='pci' bus='0x00' slot='0x02' function='0x2'/></controller>
<interface type='network'><address type='pci' bus='0x01' slot='0x00'/></interface>
<disk type='file' device='disk'><address type='pci' bus='0x03' slot='0x00'/></disk>
<video><address type='pci' bus='0x00' slot='0x01'/></video>
</devices></domain>"""


def proxy(xml=DOMAIN):
    from vrtManager.instance import wvmInstance

    p = wvmInstance.__new__(wvmInstance)
    p._XMLDesc = MagicMock(return_value=xml)
    p._defineXML = MagicMock()
    return p


class PcieSlotsTests(SimpleTestCase):
    def test_a_port_no_device_sits_behind_is_free(self):
        self.assertEqual(proxy().get_pcie_slots(), (3, 1))

    def test_a_port_numbered_above_nine_is_matched_to_its_hex_bus(self):
        ports = "".join(f"<controller type='pci' index='{i}' model='pcie-root-port'/>" for i in range(1, 13))
        xml = (f"<domain><devices>{ports}<disk type='file' device='disk'><address type='pci' bus='0x0a'/></disk>"
               "<interface type='network'><address type='pci' bus='0x0c'/></interface></devices></domain>")
        self.assertEqual(proxy(xml).get_pcie_slots(), (12, 10))

    def test_a_machine_without_ports_has_none(self):
        self.assertIsNone(proxy("<domain><devices><video/></devices></domain>").get_pcie_slots())

    def test_added_ports_are_bare_for_libvirt_to_number(self):
        p = proxy()
        p.add_pcie_slots(4)
        (defined,), _ = p._defineXML.call_args
        ports = etree.fromstring(defined).findall("devices/controller[@model='pcie-root-port']")
        self.assertEqual([port.get("index") for port in ports], ["1", "2", "3", None, None, None, None])


class AddPcieSlotsViewTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("pa-admin", "pa@example.com", "x")
        compute = Compute.objects.create(name="pa", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="pa-vm",
                                                uuid="aaaaaaaa-8888-2222-3333-444444444444")
        self.url = reverse("instances:add_pcie_slots", args=[self.instance.id])

    def post(self, status=1, slots=(7, 0), user=None):
        self.client.force_login(user or self.admin)
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = status
            wvm.return_value.get_pcie_slots.return_value = slots
            response = self.client.post(self.url, HTTP_REFERER=reverse("instances:instance", args=[self.instance.id]))
        return response, wvm.return_value.add_pcie_slots, [str(m) for m in get_messages(response.wsgi_request)]

    def test_a_running_vm_gets_them_at_its_next_start(self):
        _response, add, texts = self.post(status=1)
        add.assert_called_once_with(4)
        self.assertEqual(texts, ["4 PCIe slots added: the VM gets them at its next start"])
        self.assertTrue(Logs.objects.get(instance="pa-vm").success)

    def test_a_shut_off_vm_has_them_at_once(self):
        _response, _add, texts = self.post(status=5)
        self.assertEqual(texts, ["4 PCIe slots added"])

    def test_a_machine_without_pcie_slots_is_refused(self):
        _response, add, texts = self.post(slots=None)
        add.assert_not_called()
        self.assertEqual(texts, ["The VM's machine has no PCIe slots to add"])

    def test_only_a_superuser_adds_them(self):
        user = get_user_model().objects.create_user("pa-user", password="x")
        response, add, _texts = self.post(user=user)
        self.assertEqual(response.status_code, 403)
        add.assert_not_called()
