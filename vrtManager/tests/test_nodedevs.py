"""The host's node devices as vrtManager lists them: PCI devices by IOMMU
group and USB devices, each with what the host has on it and the VMs
that name it. Node device XML as libvirt 11.10 writes it; the connection
is a mock, libvirt's test driver has no node devices."""

from unittest.mock import MagicMock

import libvirt
from lxml import etree
from django.test import SimpleTestCase

from vrtManager import util
from vrtManager.connection import wvmConnect
from vrtManager.nodedevs import check_hostdevs, hostdev_problems, node_devices, pci_address, usb_unmatched
from vrtManager.tests.fakes import NODES, PCI_0A, USB_1_3, node, pci, vm

PCI_01 = "<hostdev mode='subsystem' type='pci'><source><address domain='0x0000' bus='0x00' slot='0x01' function='0x0'/></source></hostdev>"


USB_MODEL = "<hostdev mode='subsystem' type='usb'><source><vendor id='0x0627'/><product id='0x0001'/></source></hostdev>"


def devices(nodes=NODES, domains=()):
    conn = wvmConnect.__new__(wvmConnect)
    conn.wvm = MagicMock(**{"listAllDevices.return_value": [node(*n) for n in nodes],
                            "listAllDomains.return_value": list(domains)})
    return node_devices(conn)


class UsbUnmatchedTests(SimpleTestCase):
    """libvirt does not start a VM whose USB device the host does not have
    as named: one replugged gets another address, a second of a model makes
    a model-only name ambiguous."""

    def problems(self, source, restore=False):
        tree = etree.fromstring(f"<domain><devices>{source}</devices></domain>")
        return [util.render(m["text"], m["values"], str) for m in usb_unmatched([tree], devices()[1], restore)]

    def test_a_device_named_as_the_host_has_it_is_fine(self):
        self.assertEqual(self.problems(USB_1_3), [])

    def test_a_device_not_at_its_address_is_not_on_the_host(self):
        gone = USB_MODEL.replace("</source>", "<address bus='1' device='9'/></source>")
        self.assertEqual(self.problems(gone), ["USB device 0627:0001 at 1/9 is not on the host"])
        optional = gone.replace("<source>", "<source startupPolicy='optional'>")
        self.assertEqual(self.problems(optional), [])

    def test_a_model_the_host_has_two_of_needs_an_address(self):
        self.assertEqual(self.problems(USB_MODEL),
                         ["the host has 2 of USB device 0627:0001: name the one to give by its address"])

    def test_a_restore_drops_a_missing_requisite_device(self):
        requisite = USB_MODEL.replace("<source>", "<source startupPolicy='requisite'>")
        requisite = requisite.replace("</source>", "<address bus='1' device='9'/></source>")
        self.assertEqual(self.problems(requisite), ["USB device 0627:0001 at 1/9 is not on the host"])
        self.assertEqual(self.problems(requisite, restore=True), [])

    def test_an_address_libvirt_found_is_tried_then_the_model(self):
        found = USB_MODEL.replace("<source>", "<source autoAddress='yes'>")
        self.assertEqual(self.problems(found.replace("</source>", "<address bus='1' device='3'/></source>")), [])
        self.assertEqual(self.problems(found.replace("</source>", "<address bus='1' device='9'/></source>")),
                         ["the host has 2 of USB device 0627:0001: name the one to give by its address"])

    def test_a_found_address_still_there_is_the_device_checked(self):
        conn = wvmConnect.__new__(wvmConnect)
        conn.wvm = MagicMock(**{"listAllDevices.return_value": [node(*n) for n in NODES],
                                "listAllDomains.return_value": [vm("db-1", USB_1_3)]})
        found = USB_MODEL.replace("<source>", "<source autoAddress='yes'>").replace("</source>", "<address bus='1' device='2'/></source>")
        check_hostdevs(conn, "kiosk-1", [etree.fromstring(f"<domain><devices>{found}</devices></domain>")], restore=True)

    def test_ids_in_decimal_are_read_as_libvirt_reads_them(self):
        decimal = "<hostdev mode='subsystem' type='usb'><source><vendor id='1575'/><product id='1'/>" \
                  "<address bus='1' device='3'/></source></hostdev>"
        self.assertEqual(self.problems(decimal), [])
        self.assertEqual(self.problems(decimal.replace("'1575'", "' +0x0627'")), [])

    def test_a_revert_checks_them_too(self):
        conn = wvmConnect.__new__(wvmConnect)
        conn.wvm = MagicMock(**{"listAllDevices.return_value": [node(*n) for n in NODES], "listAllDomains.return_value": []})
        tree = etree.fromstring(f"<domain><devices>{USB_MODEL}</devices></domain>")
        with self.assertRaisesRegex(util.OperationError, "the host has 2 of USB device 0627:0001"):
            check_hostdevs(conn, "kiosk-1", [tree])


class StartCheckTests(SimpleTestCase):
    """A start checks the host devices of the definition it starts from."""

    def proxy(self, persistent, saved=None):
        from vrtManager.instance import wvmInstance

        proxy = wvmInstance.__new__(wvmInstance)
        proxy.wvm = MagicMock(**{"listAllDevices.return_value": [node(*n) for n in NODES], "listAllDomains.return_value": []})
        proxy.instance = MagicMock(**{"name.return_value": "kiosk-1", "hasManagedSaveImage.return_value": int(saved is not None),
                                      "XMLDesc.return_value": f"<domain><devices>{persistent}</devices></domain>",
                                      "managedSaveGetXMLDesc.return_value": f"<domain><devices>{saved}</devices></domain>"})
        return proxy

    def test_the_host_s_own_nic_refuses_the_start(self):
        own_nic = PCI_01.replace("0x01", "0x06")
        with self.assertRaisesRegex(util.OperationError, "holds the host's eth0"):
            self.proxy(own_nic).check_start_hostdevs()
        self.proxy(PCI_0A).check_start_hostdevs()  # bound to vfio-pci, alone in its group

    def test_a_restore_checks_the_saved_state_a_fresh_boot_the_definition(self):
        proxy = self.proxy(PCI_0A, saved=USB_MODEL)
        with self.assertRaisesRegex(util.OperationError, "the host has 2 of"):
            proxy.check_start_hostdevs()
        proxy.check_start_hostdevs(restore=False)

    def test_a_restore_drops_a_missing_requisite_device_a_boot_does_not(self):
        gone = USB_MODEL.replace("<source>", "<source startupPolicy='requisite'>")
        gone = gone.replace("</source>", "<address bus='1' device='9'/></source>")
        self.proxy(gone, saved=gone).check_start_hostdevs()
        with self.assertRaisesRegex(util.OperationError, "is not on the host"):
            self.proxy(gone, saved=gone).check_start_hostdevs(restore=False)


class ResourceLanguageTests(SimpleTestCase):
    def test_a_usb_device_the_host_has_is_named_in_the_reader_s_language(self):
        from django.utils import translation

        with translation.override("tr"):
            pci_devices, _ = devices()
        self.assertEqual(pci_devices[-1]["resources"], ["USB aygıtı 1/2 (QEMU Tablet)", "USB aygıtı 1/3 (QEMU Tablet)"])


class NodeDevicesTests(SimpleTestCase):
    def test_pci_devices_by_group_with_what_the_host_has_on_them(self):
        pci_devices, _ = devices()
        self.assertEqual([(d["address"], d["group"]) for d in pci_devices],
                         [("0000:00:02.0", 2), ("0000:00:03.0", 2), ("0000:00:06.0", 3), ("0000:00:0a.0", 4), ("0000:00:01.0", None)])
        gpu, disk, nic, spare, _ = pci_devices
        # a graphics card's primary node is the host's; its render node is not a resource of its own
        self.assertEqual((gpu["resources"], disk["resources"], nic["resources"], spare["resources"]),
                         (["/dev/dri/card0"], ["/dev/vda"], ["eth0"], []))
        self.assertEqual((nic["kind"], nic["driver"], nic["ids"]), ("Network controller", "virtio-pci", "1af4:1000"))

    def test_usb_devices_with_their_classes_hubs_and_same_models(self):
        _, (hub, tablet_2, tablet_3) = devices()
        self.assertEqual((hub["kinds"], hub["same_model"]), (["Hub"], False))
        self.assertEqual((tablet_2["kinds"], tablet_2["same_model"], tablet_3["same_model"]), (["Human interface"], True, True))

    def test_the_vms_that_name_a_device(self):
        pci_devices, (_, tablet_2, tablet_3) = devices(domains=[vm("db-1", PCI_0A + USB_1_3), vm("kiosk-1", USB_MODEL)])
        self.assertEqual([d["vms"] for d in pci_devices], [[], [], [], ["db-1"], []])
        # by address: that device; by model only: any device of the model
        self.assertEqual((tablet_3["vms"], tablet_3["by_model"]), (["db-1"], ["kiosk-1"]))
        self.assertEqual((tablet_2["vms"], tablet_2["by_model"]), ([], ["kiosk-1"]))

    def test_a_usb_controller_holds_the_usb_devices_below_it(self):
        pci_devices, (hub, tablet_2, _) = devices(domains=[vm("kiosk-1", USB_1_3)])
        controller = [d for d in pci_devices if d["address"] == "0000:00:01.0"][0]
        # its root hub is no device of the host's; the tablets are, one given to a VM
        self.assertEqual(controller["resources"], ["USB device 1/2 (QEMU Tablet)", "USB device 1/3 (QEMU Tablet)"])
        self.assertEqual((hub["controller"], tablet_2["controller"]), ("0000:00:01.0", "0000:00:01.0"))

    def test_a_usb_device_on_a_controller_given_to_a_vm_is_not_given_to_another(self):
        pci_devices, usb_devices = devices(domains=[vm("db-1", PCI_01)])
        reasons = [util.render(m["text"], m["values"], str) for m in hostdev_problems(
            "kiosk-1", pci_devices, usb_devices, set(), [("0x0627", "0x0001", (1, 2))])]
        self.assertIn("USB device 1/2 (QEMU Tablet) is on the PCI controller 0000:00:01.0, given to db-1", reasons)

    def test_a_usb_device_is_named_as_libvirt_picks_one(self):
        def named(hostdev):
            _, (_, tablet_2, tablet_3) = devices(domains=[vm("v", hostdev)])
            return [(d["vms"], d["by_model"]) for d in (tablet_2, tablet_3)]
        # an address with other IDs: another device now at that address
        other = USB_1_3.replace("0x0627", "0x046d")
        address_only = "<hostdev mode='subsystem' type='usb'><source><address bus='1' device='2'/></source></hostdev>"
        self.assertEqual(named(other), [([], []), ([], [])])
        self.assertEqual(named(address_only), [(["v"], []), ([], [])])
        self.assertEqual(named(USB_MODEL), [([], ["v"]), ([], ["v"])])

    def test_a_pci_device_named_as_a_nic_or_only_for_the_next_start(self):
        nic = ("<interface type='hostdev'><source><address type='pci' domain='0x0000' bus='0x00' slot='0x06' function='0x0'/>"
               "</source></interface>")
        pci_devices, _ = devices(domains=[vm("nic-1", nic), vm("next-1", "", saved=PCI_0A)])
        self.assertEqual({d["address"]: d["vms"] for d in pci_devices if d["vms"]},
                         {"0000:00:06.0": ["nic-1"], "0000:00:0a.0": ["next-1"]})

    def test_sr_iov_functions_and_unnamed_hardware(self):
        vf = pci("0x0b", "", "0x020000", group=5)[1].replace(
            "<product id='0x1000'></product>", "<product id='0x10ed'/>").replace(
            "</capability></device>", "<capability type='phys_function'><address domain='0x0000' bus='0x00' slot='0x0a'"
                                      " function='0x0'/></capability></capability></device>")
        pf = NODES[8][1].replace("</capability></device>", "<capability type='virt_functions' maxCount='7'><address domain='0x0000'"
                                 " bus='0x00' slot='0x0b' function='0x0'/></capability></capability></device>")
        pci_devices, _ = devices(nodes=[("pci_0000_00_0a_0", pf), ("pci_0000_00_0b_0", vf)])
        self.assertEqual([(d["physfn"], d["vfs"], d["product"]) for d in pci_devices],
                         [("", 1, "Ethernet controller"), ("0000:00:0a.0", 0, "0x10ed")])

    def test_a_device_gone_meanwhile_is_left_out_other_errors_are_raised(self):
        for code, raised in ((libvirt.VIR_ERR_NO_NODE_DEVICE, False), (libvirt.VIR_ERR_OPERATION_FAILED, True)):
            err = libvirt.libvirtError("gone")
            err.get_error_code = lambda code=code: code
            gone = node("pci_0000_00_0b_0", "")
            gone.XMLDesc.side_effect = err
            conn = wvmConnect.__new__(wvmConnect)
            conn.wvm = MagicMock(**{"listAllDevices.return_value": [gone, node(*NODES[0])], "listAllDomains.return_value": []})
            with self.subTest(code=code):
                if raised:
                    self.assertRaises(libvirt.libvirtError, node_devices, conn)
                else:
                    self.assertEqual([d["address"] for d in node_devices(conn)[0]], ["0000:00:06.0"])

    def test_a_pci_address_from_libvirts_hex_or_numbers(self):
        self.assertEqual(pci_address("0x0000", "0x00", "0x1f", "0x3"), pci_address(0, 0, 31, 3))
        self.assertEqual(pci_address(0, 0, 31, 3), "0000:00:1f.3")
