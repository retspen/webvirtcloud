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
from vrtManager import util
from vrtManager.nodedevs import _pci, check_hostdevs, hostdev_problems, pci_problems
from vrtManager.tests.fakes import IOMMU_NODES
from vrtManager.util import OperationError


def inventory(vms=()):
    """The host's PCI devices, as a list; vms: (VM, its PCI addresses)."""
    children = {}
    for name, node in IOMMU_NODES.items():
        children.setdefault(node.findtext("parent"), []).append(name)
    users = [(vm, set(addresses), []) for vm, addresses in vms]
    return [_pci(name, node, IOMMU_NODES, children, users) for name, node in IOMMU_NODES.items()
            if node.find("capability").get("type") == "pci"]


def problems(address, managed=(), vms=()):
    devices = {d["address"]: d for d in inventory(vms)}
    return " ".join(util.render(m["text"], m["values"], str)
                    for m in pci_problems("web-1", devices[address], devices, {address, *managed}))


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
        reasons = [util.render(m["text"], m["values"], str)
                   for m in hostdev_problems("web-1", inventory(), [], {"0000:00:1f.0"}, [])]
        self.assertEqual(reasons, ["PCI device 0000:00:1f.0 is not on the host"])


class DefinitionsTests(SimpleTestCase):
    """A revert restores two definitions; the VM starts from one of them."""

    def check(self, *devices_per_definition):
        conn = MagicMock()
        conn.wvm.listAllDevices.return_value = [MagicMock(**{"name.return_value": name,
                                                             "XMLDesc.return_value": etree.tostring(node)})
                                                for name, node in IOMMU_NODES.items()]
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
