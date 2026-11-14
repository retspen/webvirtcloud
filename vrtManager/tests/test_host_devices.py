"""A VM's host devices in vrtManager: USB devices given and taken back,
each named once whether the running VM or its next start has it, PCI
devices plugged into a running VM, and a VM with any is not migrated."""

import unittest
from unittest.mock import MagicMock

import libvirt
from django.test import SimpleTestCase
from lxml import etree

from vrtManager.instance import wvmInstance
from vrtManager.tests.fakes import FakeSource, by_model, destination, domain, with_disks
from vrtManager.util import OperationError

MIGRATABLE = libvirt.VIR_DOMAIN_XML_MIGRATABLE


CONTROLLER = "<controller type='usb' model='qemu-xhci'/>"


PCI_05 = ("<hostdev mode='subsystem' type='pci' managed='yes'><source>"
          "<address domain='0x0000' bus='0x05' slot='0x00' function='0x0'/></source></hostdev>")


def vm(running, saved, active=True, migratable=None):
    """A wvmInstance whose running VM is running, as XMLDesc gives it (and as
    the migratable XML marks it), and whose next start is saved."""
    proxy = wvmInstance.__new__(wvmInstance)
    proxy._read_cache = None
    proxy.instance = MagicMock(**{"isActive.return_value": active, "hasManagedSaveImage.return_value": 0,
                                  "info.return_value": [libvirt.VIR_DOMAIN_RUNNING if active else libvirt.VIR_DOMAIN_SHUTOFF]})

    def describe(flags=0):
        if flags & libvirt.VIR_DOMAIN_XML_INACTIVE:
            return saved
        return migratable if flags & MIGRATABLE and migratable else running
    proxy.instance.XMLDesc.side_effect = describe
    return proxy


class UsbHostdevTests(SimpleTestCase):
    def test_a_device_chosen_by_model_is_one_row_with_the_device_it_holds(self):
        # the running VM writes the address libvirt resolved; only its migratable XML marks it
        proxy = vm(domain(CONTROLLER, by_model("<address bus='1' device='3'/>")), domain(CONTROLLER, by_model()),
                   migratable=domain(CONTROLLER, by_model("<address bus='1' device='3'/>", " autoAddress='yes'")))
        usb, pci, others = proxy.get_hostdevs()
        self.assertEqual(usb, [{"vendor": "0x0627", "product": "0x0001", "address": None, "now": (1, 3), "next": True}])
        self.assertEqual((pci, others), ([], []))

    def test_a_device_is_taken_from_each_definition_as_it_describes_it(self):
        proxy = vm(domain(CONTROLLER, by_model("<address bus='1' device='3'/>")), domain(CONTROLLER, by_model()),
                   migratable=domain(CONTROLLER, by_model("<address bus='1' device='3'/>", " autoAddress='yes'")))
        proxy.delete_usb_hostdev(("0x0627", "0x0001", None))
        live, config = proxy.instance.detachDeviceFlags.call_args_list
        self.assertEqual(live.args[1], libvirt.VIR_DOMAIN_AFFECT_LIVE)
        self.assertEqual(etree.fromstring(live.args[0]).xpath("string(source/address/@device)"), "3")
        self.assertEqual((config.args[1], etree.fromstring(config.args[0]).find("source/address")),
                         (libvirt.VIR_DOMAIN_AFFECT_CONFIG, None))
        with self.assertRaisesRegex(OperationError, "no such USB device"):
            proxy.delete_usb_hostdev(("0x0627", "0x0001", (1, 2)))

    def test_a_device_is_given_by_model_or_by_address_with_a_usb_controller(self):
        proxy = vm(domain(CONTROLLER), domain(CONTROLLER))
        proxy.add_usb_hostdev("0x0627", "0x0001", (1, 3))
        added = etree.fromstring(proxy.instance.attachDeviceFlags.call_args.args[0])
        self.assertEqual((added.get("type"), added.xpath("string(source/vendor/@id)"), added.xpath("string(source/address/@device)")),
                         ("usb", "0x0627", "3"))
        for xml in (domain(), domain("<controller type='usb' model='none'/>")):
            proxy = vm(xml, xml, active=False)
            with self.subTest(xml=xml), self.assertRaisesRegex(OperationError, "no USB controller"):
                proxy.add_usb_hostdev("0x0627", "0x0001")
            proxy.instance.attachDeviceFlags.assert_not_called()

    def test_a_vm_with_a_saved_state_keeps_its_usb_devices(self):
        proxy = vm(domain(CONTROLLER), domain(CONTROLLER, by_model()), active=False)
        proxy.instance.hasManagedSaveImage.return_value = 1
        for change in (lambda: proxy.add_usb_hostdev("0x0627", "0x0001"),
                       lambda: proxy.delete_usb_hostdev(("0x0627", "0x0001", None))):
            with self.assertRaisesRegex(OperationError, "saved state does not change its USB devices"):
                change()
        proxy.instance.attachDeviceFlags.assert_not_called()
        proxy.instance.detachDeviceFlags.assert_not_called()

    def test_a_usb_change_that_fails_half_way_says_where_the_device_is(self):
        # the running VM let it go, its next start's removal failed
        xml = {"running": domain(CONTROLLER, by_model("<address bus='1' device='3'/>")),
               "saved": domain(CONTROLLER, by_model("<address bus='1' device='3'/>"))}
        proxy = vm("", "")
        proxy.instance.XMLDesc.side_effect = lambda flags=0: xml["saved" if flags & libvirt.VIR_DOMAIN_XML_INACTIVE else "running"]

        def detach(_xml, affect):
            if affect == libvirt.VIR_DOMAIN_AFFECT_CONFIG:
                raise libvirt.libvirtError("cannot save the definition")
            xml["running"] = domain(CONTROLLER)
        proxy.instance.detachDeviceFlags.side_effect = detach
        with self.assertRaisesRegex(OperationError, "cannot save the definition; USB device 0627:0001 at 1/3: "
                                                    "the running VM does not have it, its next start has it"):
            proxy.delete_usb_hostdev(("0x0627", "0x0001", (1, 3)))
        # a hot plug: the running VM got it, its next start did not
        xml["running"], xml["saved"] = domain(CONTROLLER, by_model("<address bus='1' device='3'/>")), domain(CONTROLLER)
        proxy.instance.attachDeviceFlags.side_effect = libvirt.libvirtError("cannot save the definition")
        with self.assertRaisesRegex(OperationError, "the running VM has it, its next start does not have it"):
            proxy.add_usb_hostdev("0x0627", "0x0001", (1, 3))

    def test_a_device_the_host_has_one_of_is_given_by_model(self):
        proxy = vm(domain(CONTROLLER), domain(CONTROLLER))
        proxy.add_usb_hostdev("0x0627", "0x0001")
        self.assertIsNone(etree.fromstring(proxy.instance.attachDeviceFlags.call_args.args[0]).find("source/address"))

    def test_other_host_devices_as_the_running_vm_and_its_next_start_have_them(self):
        pci = "<hostdev mode='subsystem' type='pci'><source><address domain='0x0000' bus='0x00' slot='0x0a' function='0x0'/></source></hostdev>"
        nic = "<interface type='hostdev'><source><address type='pci' domain='0x0000' bus='0x00' slot='0x0b' function='0x0'/></source></interface>"
        network_nic = ("<interface type='network'><source network='sriov'/><actual type='hostdev'><source>"
                       "<address type='pci' domain='0x0000' bus='0x00' slot='0x0c' function='0x1'/></source></actual></interface>")
        mdev = "<hostdev mode='subsystem' type='mdev'><source><address uuid='{}'/></source></hostdev>"
        running = domain(pci, nic, network_nic, mdev.format("00000000-0000-4000-8000-00000000a001"))
        _, pci_rows, others = vm(running, domain(nic, mdev.format("00000000-0000-4000-8000-00000000a002"))).get_hostdevs()
        self.assertEqual(pci_rows, [{"address": "0000:00:0a.0", "now": True, "next": False, "managed": False}])
        self.assertEqual(others, [{"type": "nic", "address": "0000:00:0b.0", "now": True, "next": True},
                                  {"type": "nic", "address": "0000:00:0c.1", "now": True, "next": False},
                                  {"type": "mdev", "address": "00000000-0000-4000-8000-00000000a001", "now": True, "next": False},
                                  {"type": "mdev", "address": "00000000-0000-4000-8000-00000000a002", "now": False, "next": True}])

    def test_a_shut_off_vm_gets_a_pci_device_for_its_next_start(self):
        proxy = vm("", domain(), active=False)
        proxy.add_pci_hostdev("0000:05:00.0")
        xml, flags = proxy.instance.attachDeviceFlags.call_args.args
        self.assertEqual(flags, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        self.assertEqual((etree.fromstring(xml).get("managed"), dict(etree.fromstring(xml).find("source/address").attrib)),
                         ("yes", {"domain": "0x0000", "bus": "0x05", "slot": "0x00", "function": "0x0"}))
        proxy = vm("", domain(PCI_05), active=False)
        self.assertFalse(proxy.delete_pci_hostdev("0000:05:00.0"))
        self.assertEqual([c.args[1] for c in proxy.instance.detachDeviceFlags.call_args_list], [libvirt.VIR_DOMAIN_AFFECT_CONFIG])
        with self.assertRaisesRegex(OperationError, "no PCI device 0000:06:00.0"):
            proxy.delete_pci_hostdev("0000:06:00.0")

    def test_a_paused_vm_or_one_with_a_saved_state_keeps_its_pci_devices(self):
        paused = vm(domain(PCI_05), domain(PCI_05))
        paused.instance.info.return_value = [libvirt.VIR_DOMAIN_PAUSED]
        saved = vm("", domain(PCI_05), active=False)
        saved.instance.hasManagedSaveImage.return_value = 1
        for name, proxy in (("paused", paused), ("saved", saved)):
            for change in (proxy.add_pci_hostdev, proxy.delete_pci_hostdev):
                with self.subTest(vm=name, change=change.__name__), self.assertRaisesRegex(OperationError, "runs, or is shut off"):
                    change("0000:05:00.0")
            proxy.instance.attachDeviceFlags.assert_not_called()
            proxy.instance.detachDeviceFlags.assert_not_called()

    def test_a_nic_that_is_a_host_device_is_left_to_the_xml_editor(self):
        nic = "<interface type='hostdev'><mac address='52:54:00:00:00:0a'/><source><address type='pci' bus='0x00' slot='0x0a'/></source></interface>"
        proxy = vm(domain(nic), domain(nic))
        with self.assertRaisesRegex(OperationError, "XML editor"):
            proxy.delete_network("52:54:00:00:00:0a")
        with self.assertRaisesRegex(OperationError, "XML editor"):
            proxy.change_network("52:54:00:00:00:0a", "52:54:00:00:00:0b", "default", "net", "virtio", "")
        proxy.instance.detachDeviceFlags.assert_not_called()

    def test_a_clone_gets_no_host_device_and_its_nics_keep_their_numbers(self):
        proxy = vm("", domain(by_model(),
                              "<interface type='hostdev'><mac address='52:54:00:00:00:0a'/></interface>",
                              "<interface type='network'><mac address='52:54:00:00:00:0b'/><source network='default'/></interface>"))
        proxy.get_instances = lambda: []
        tree, _ = proxy._clone_definition({"name": "kiosk-2", "clone-net-mac-1": "52:54:00:00:00:1b"},
                                          "99999999-2222-3333-4444-555555555555")
        self.assertEqual(tree.xpath("devices/hostdev"), [])
        self.assertEqual(tree.xpath("devices/interface/mac/@address"), ["52:54:00:00:00:1b"])


class RunningVM:
    """A running VM whose definitions change as libvirt changes them: the
    running one and the next start's, each with the PCI device or not.
    fail: the affect flag whose change libvirt fails, after doing it or not;
    keeps: the guest does not let the device go."""

    def __init__(self, now=True, later=True, fail=None, done=False, keeps=False, machine="pc-i440fx-10.1"):
        self.has = {libvirt.VIR_DOMAIN_AFFECT_LIVE: now, libvirt.VIR_DOMAIN_AFFECT_CONFIG: later}
        self.fail, self.done, self.keeps, self.machine = fail, done, keeps, machine
        self.proxy = vm("", "")
        self.proxy.instance.XMLDesc.side_effect = self.describe
        self.proxy.instance.attachDeviceFlags.side_effect = lambda xml, flags: self.change(flags, True)
        self.proxy.instance.detachDeviceFlags.side_effect = lambda xml, flags: self.change(flags, False)

    def describe(self, flags=0):
        saved = flags & libvirt.VIR_DOMAIN_XML_INACTIVE
        has = self.has[libvirt.VIR_DOMAIN_AFFECT_CONFIG if saved else libvirt.VIR_DOMAIN_AFFECT_LIVE]
        return f"<domain><os><type machine='{self.machine}'>hvm</type></os><devices>{PCI_05 if has else ''}</devices></domain>"

    def change(self, flags, adding):
        for affect in (libvirt.VIR_DOMAIN_AFFECT_LIVE, libvirt.VIR_DOMAIN_AFFECT_CONFIG):
            if flags & affect:
                if affect == self.fail:
                    if self.done:
                        self.has[affect] = adding
                    raise libvirt.libvirtError("refused")
                if adding or not (self.keeps and affect == libvirt.VIR_DOMAIN_AFFECT_LIVE):
                    self.has[affect] = adding


class PciHotplugTests(SimpleTestCase):
    def test_a_running_vm_gets_it_at_once_and_for_its_next_start(self):
        running = RunningVM(now=False, later=False)
        running.proxy.add_pci_hostdev("0000:05:00.0")
        self.assertEqual(running.proxy.instance.attachDeviceFlags.call_args.args[1],
                         libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        self.assertEqual(list(running.has.values()), [True, True])

    def test_a_hot_plug_that_fails_says_where_the_device_is(self):
        cases = ((libvirt.VIR_DOMAIN_AFFECT_CONFIG, False, "the running VM has it, its next start does not have it"),
                 (libvirt.VIR_DOMAIN_AFFECT_CONFIG, True, "the running VM has it, its next start has it"),
                 (libvirt.VIR_DOMAIN_AFFECT_LIVE, False, "the running VM does not have it, its next start does not have it"))
        for fail, done, where in cases:
            # libvirt plugs into the running VM first, then saves the next start
            running = RunningVM(now=False, later=False, fail=fail, done=done)
            if fail == libvirt.VIR_DOMAIN_AFFECT_CONFIG:
                running.has[libvirt.VIR_DOMAIN_AFFECT_LIVE] = True
            with self.subTest(where=where), self.assertRaisesRegex(OperationError, f"refused; PCI device 0000:05:00.0: {where}"):
                running.proxy.add_pci_hostdev("0000:05:00.0")

    def test_a_hot_plug_whose_outcome_cannot_be_read_says_so(self):
        running = RunningVM(now=False, later=False)
        running.proxy.instance.attachDeviceFlags.side_effect = libvirt.libvirtError("connection reset")
        running.proxy.instance.XMLDesc.side_effect = libvirt.libvirtError("connection reset")
        with self.assertRaisesRegex(OperationError, "connection reset; whether the VM has PCI device 0000:05:00.0 now is not known"):
            running.proxy.add_pci_hostdev("0000:05:00.0")

    def test_a_vm_that_stops_meanwhile_is_said_to_be_not_running(self):
        running = RunningVM(now=False, later=False, fail=libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        running.proxy.instance.isActive.return_value = False  # its live XML is then the inactive one
        with self.assertRaisesRegex(OperationError, "the VM is not running, its next start does not have it"):
            running.proxy.add_pci_hostdev("0000:05:00.0")

    def test_a_running_vm_lets_it_go_as_its_guest_does(self):
        running = RunningVM()
        self.assertFalse(running.proxy.delete_pci_hostdev("0000:05:00.0"))
        self.assertEqual(list(running.has.values()), [False, False])
        # not yet: the request stands, the next start no longer has it
        running = RunningVM(keeps=True)
        self.assertTrue(running.proxy.delete_pci_hostdev("0000:05:00.0"))
        self.assertEqual(list(running.has.values()), [True, False])

    def test_a_guest_that_refuses_keeps_it_for_its_next_start_too(self):
        running = RunningVM(fail=libvirt.VIR_DOMAIN_AFFECT_LIVE)
        with self.assertRaisesRegex(OperationError, "refused; .*the running VM has it, its next start has it"):
            running.proxy.delete_pci_hostdev("0000:05:00.0")
        self.assertEqual(list(running.has.values()), [True, True])
        # removed from the running VM, then an error: said, and the next start keeps it
        running = RunningVM(fail=libvirt.VIR_DOMAIN_AFFECT_LIVE, done=True)
        with self.assertRaisesRegex(OperationError, "the running VM does not have it, its next start has it"):
            running.proxy.delete_pci_hostdev("0000:05:00.0")

    def test_a_failed_removal_from_the_next_start_of_a_running_vm_is_said(self):
        running = RunningVM(now=False, later=True, fail=libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        with self.assertRaisesRegex(OperationError, "the running VM does not have it, its next start has it"):
            running.proxy.delete_pci_hostdev("0000:05:00.0")

    def test_a_removal_whose_outcome_cannot_be_read_says_so(self):
        running = RunningVM()
        reads = []

        def describe(flags=0):  # the reads before the removal work, the one after it does not
            reads.append(flags)
            if len(reads) > 2:
                raise libvirt.libvirtError("connection reset")
            return running.describe(flags)
        running.proxy.instance.XMLDesc.side_effect = describe
        with self.assertRaisesRegex(OperationError, "connection reset; whether the VM has PCI device 0000:05:00.0 now is not known"):
            running.proxy.delete_pci_hostdev("0000:05:00.0")

    def test_a_next_start_that_keeps_it_after_the_running_vm_let_it_go_is_said(self):
        for keeps, where in ((False, "the running VM does not have it, its next start has it"),
                             (True, "the running VM has it, its next start has it")):
            running = RunningVM(fail=libvirt.VIR_DOMAIN_AFFECT_CONFIG, keeps=keeps)
            with self.subTest(keeps=keeps), self.assertRaisesRegex(OperationError, where):
                running.proxy.delete_pci_hostdev("0000:05:00.0")

    def test_a_device_in_one_definition_only_is_taken_from_it(self):
        for now, later in ((True, False), (False, True)):
            running = RunningVM(now=now, later=later)
            with self.subTest(now=now, later=later):
                self.assertFalse(running.proxy.delete_pci_hostdev("0000:05:00.0"))
                self.assertEqual(list(running.has.values()), [False, False])
                self.assertEqual(running.proxy.instance.detachDeviceFlags.call_count, 1)


class MigrationTests(unittest.TestCase):
    def test_a_vm_with_host_devices_is_not_migrated(self):
        for devices, state in ((by_model(), 1), (by_model(), 5), ("<hostdev mode='subsystem' type='pci'/>", 1)):
            source = FakeSource(state, xml=with_disks(devices))
            with self.subTest(state=state), self.assertRaisesRegex(OperationError, "host devices cannot be migrated"):
                destination().moveto(source, "vm", live=state == 1, unsafe=False, offline=state == 5)
            self.assertEqual(source.instance.calls, [])
