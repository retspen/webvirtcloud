"""Which PCI devices of a host a VM can be given: an endpoint in an IOMMU
group, without the host's own network interfaces or disks on it, that no
other VM names; the other endpoints of its group are managed devices of the
same definition, or have no driver or vfio-pci, and no other VM has any of
them; bridges stay with pcieport. Each definition of a snapshot is checked
on its own. Node XML as libvirt 11.10 writes it on a q35 host with an
emulated IOMMU."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase
from lxml import etree
from vrtManager.nodedevs import _pci, check_hostdevs, hostdev_problems, pci_problems
from vrtManager.util import OperationError


def device(slot, product, code, driver, group, members=None, bridge=False):
    """A PCI device on bus 0 at slot, in IOMMU group with the slots members (its own by default)."""
    members = members or [slot]
    addresses = "".join(f"<address domain='0x0000' bus='0x00' slot='0x{m:02x}' function='0x0'/>" for m in members)
    driver_xml = f"<driver><name>{driver}</name></driver>" if driver else ""
    bridge_xml = "<capability type='pci-bridge'/>" if bridge else ""
    xml = (f"<device><name>pci_0000_00_{slot:02x}_0</name><parent>computer</parent>{driver_xml}"
           f"<capability type='pci'><class>{code}</class><domain>0</domain><bus>0</bus><slot>{slot}</slot><function>0</function>"
           f"<product id='0x0001'>{product}</product><vendor id='0x8086'>Intel</vendor>{bridge_xml}"
           f"<iommuGroup number='{group}'>{addresses}</iommuGroup></capability></device>")
    return f"pci_0000_00_{slot:02x}_0", etree.fromstring(xml)


NODES = dict([
    device(0x02, "PCIe Root port", "0x060400", "pcieport", 2, bridge=True),
    device(0x03, "SATA controller", "0x010601", "ahci", 7, [0x03, 0x04, 0x05]),
    device(0x04, "SMBus controller", "0x0c0500", "i801_smbus", 7, [0x03, 0x04, 0x05]),
    device(0x05, "LPC controller", "0x060100", "lpc_ich", 7, [0x03, 0x04, 0x05]),  # class 0x06, not a bridge
    device(0x06, "Gigabit NIC", "0x020000", "e1000e", 12),
    device(0x07, "Spare NIC", "0x020000", "vfio-pci", 13),
    device(0x08, "NIC port 0", "0x020000", "vfio-pci", 14, [0x08, 0x09, 0x0a]),
    device(0x09, "NIC port 1", "0x020000", None, 14, [0x08, 0x09, 0x0a]),
    device(0x0a, "Downstream port", "0x060400", "pcieport", 14, [0x08, 0x09, 0x0a], bridge=True),
    device(0x0b, "Accelerator", "0x120000", "vfio-pci", 15, [0x0b, 0x0c]),  # 0x0c cannot be read
    device(0x0d, "GPU", "0x030000", "nouveau", 16, [0x0d, 0x0e]),
    device(0x0e, "GPU audio", "0x040300", "snd_hda_intel", 16, [0x0d, 0x0e]),
])
# what the host has below: a disk on the SATA controller, its interface on the e1000e
NODES["block_sda"] = etree.fromstring("<device><name>block_sda</name><parent>pci_0000_00_03_0</parent>"
                                      "<capability type='storage'><block>/dev/sda</block></capability></device>")
NODES["net_eth1"] = etree.fromstring("<device><name>net_eth1</name><parent>pci_0000_00_06_0</parent>"
                                     "<capability type='net'><interface>eth1</interface></capability></device>")


def inventory(vms=()):
    """The host's PCI devices, as a list; vms: (VM, its PCI addresses)."""
    children = {}
    for name, node in NODES.items():
        children.setdefault(node.findtext("parent"), []).append(name)
    users = [(vm, set(addresses), []) for vm, addresses in vms]
    return [_pci(name, node, NODES, children, users) for name, node in NODES.items()
            if node.find("capability").get("type") == "pci"]


def problems(address, managed=(), vms=()):
    devices = {d["address"]: d for d in inventory(vms)}
    return " ".join(pci_problems("web-1", devices[address], devices, {address, *managed}))


def hostdev(slot, managed="yes"):
    return (f"<hostdev mode='subsystem' type='pci' managed='{managed}'><source>"
            f"<address domain='0x0000' bus='0x00' slot='0x{slot:02x}' function='0x0'/></source></hostdev>")


class PciRulesTests(SimpleTestCase):
    def test_a_lone_endpoint_bound_to_vfio_pci_can_be_given(self):
        self.assertEqual(problems("0000:00:07.0"), "")

    def test_a_device_the_host_uses_can_not_and_how_to_free_it(self):
        reason = problems("0000:00:06.0")
        self.assertIn("holds the host's eth1", reason)
        self.assertIn("bind 0000:00:06.0 to vfio-pci on the host first", reason)

    def test_a_bridge_of_any_kind_can_not(self):
        # a PCIe port, and of the bridge class an LPC controller (a host bridge alike)
        self.assertEqual(problems("0000:00:02.0"), "PCI device 0000:00:02.0 is a bridge")
        self.assertEqual(problems("0000:00:05.0"), "PCI device 0000:00:05.0 is a bridge")

    def test_the_other_endpoints_of_its_group_must_be_free_of_the_host(self):
        # the LPC controller is of class 0x06 but no bridge: its driver keeps the group
        reason = problems("0000:00:04.0")
        self.assertIn("with 0000:00:03.0 (SATA controller), which the host (driver ahci) uses", reason)
        self.assertIn("with 0000:00:05.0 (LPC controller), which the host (driver lpc_ich) uses", reason)

    def test_unbound_and_vfio_pci_members_and_a_pcieport_bridge_keep_nothing(self):
        self.assertEqual(problems("0000:00:08.0"), "")

    def test_a_member_given_as_a_managed_device_too_is_taken_with_it(self):
        self.assertIn("with 0000:00:0e.0 (GPU audio), which the host (driver snd_hda_intel) uses", problems("0000:00:0d.0"))
        self.assertEqual(problems("0000:00:0d.0", managed={"0000:00:0e.0"}), "")

    def test_a_member_another_vm_has_or_that_cannot_be_read_keeps_the_group(self):
        self.assertIn("with 0000:00:09.0 (NIC port 1), which db-1 uses",
                      problems("0000:00:08.0", vms=[("db-1", {"0000:00:09.0"})]))
        # managed in this definition or not: another VM has it
        self.assertIn("which db-1 uses", problems("0000:00:0d.0", managed={"0000:00:0e.0"}, vms=[("db-1", {"0000:00:0e.0"})]))
        self.assertIn("with 0000:00:0c.0, which cannot be read", problems("0000:00:0b.0"))

    def test_a_device_another_vm_has_can_not(self):
        self.assertIn("is given to db-1", problems("0000:00:07.0", vms=[("db-1", {"0000:00:07.0"})]))
        self.assertEqual(problems("0000:00:07.0", vms=[("web-1", {"0000:00:07.0"})]), "")  # its own

    def test_a_device_the_host_does_not_have_can_not(self):
        reasons = hostdev_problems("web-1", inventory(), [], {"0000:00:1f.0"}, [])
        self.assertEqual(reasons, ["PCI device 0000:00:1f.0 is not on the host"])


class DefinitionsTests(SimpleTestCase):
    """A revert restores two definitions; the VM starts from one of them."""

    def check(self, *devices_per_definition):
        conn = MagicMock()
        conn.wvm.listAllDevices.return_value = [MagicMock(**{"name.return_value": name,
                                                             "XMLDesc.return_value": etree.tostring(node)})
                                                for name, node in NODES.items()]
        conn.domain_trees.return_value = []
        trees = [etree.fromstring(f"<domain><devices>{''.join(devices)}</devices></domain>") for devices in devices_per_definition]
        check_hostdevs(conn, "web-1", trees)

    def test_each_definition_takes_its_group_on_its_own(self):
        self.check([hostdev(0x0d), hostdev(0x0e)])
        # the running definition has the GPU, only the saved one its audio function
        with self.assertRaisesRegex(OperationError, "GPU audio"):
            self.check([hostdev(0x0d)], [hostdev(0x0e)])

    def test_a_member_libvirt_does_not_manage_keeps_its_host_driver(self):
        with self.assertRaisesRegex(OperationError, "which the host \\(driver snd_hda_intel\\) uses"):
            self.check([hostdev(0x0d), hostdev(0x0e, managed="no")])
