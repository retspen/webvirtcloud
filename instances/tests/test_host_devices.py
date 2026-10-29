"""A VM's host devices: USB devices of its host given and taken back, each
named once whether the running VM or its next start has it; the checks that
keep a device to one VM and away from what the host uses itself, also for a
snapshot revert; clones get none, and a VM with any is not migrated."""

import unittest
from unittest.mock import MagicMock, patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import etree, html
from nodedevs.tests.test_nodedevs import NODES, node
from vrtManager.instance import wvmInstance
from vrtManager.util import OperationError

from vrtManager.tests.test_migration import FakeSource, destination, with_disks

MIGRATABLE = libvirt.VIR_DOMAIN_XML_MIGRATABLE
CONTROLLER = "<controller type='usb' model='qemu-xhci'/>"
BY_MODEL = "<hostdev mode='subsystem' type='usb' managed='yes'><source{auto}><vendor id='0x0627'/><product id='0x0001'/>{address}</source></hostdev>"


def by_model(address="", auto=""):
    return BY_MODEL.format(address=address, auto=auto)


def domain(*devices):
    return f"<domain><name>kiosk-1</name><devices>{''.join(devices)}</devices></domain>"


def vm(running, saved, active=True, migratable=None):
    """A wvmInstance whose running VM is running, as XMLDesc gives it (and as
    the migratable XML marks it), and whose next start is saved."""
    proxy = wvmInstance.__new__(wvmInstance)
    proxy._read_cache = None
    proxy.instance = MagicMock(**{"isActive.return_value": active, "hasManagedSaveImage.return_value": 0})

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

    def test_a_pci_device_is_given_and_taken_back_only_while_the_vm_is_shut_off(self):
        proxy = vm("", domain(), active=False)
        proxy.add_pci_hostdev("0000:05:00.0")
        xml, flags = proxy.instance.attachDeviceFlags.call_args.args
        self.assertEqual(flags, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        self.assertEqual((etree.fromstring(xml).get("managed"), dict(etree.fromstring(xml).find("source/address").attrib)),
                         ("yes", {"domain": "0x0000", "bus": "0x05", "slot": "0x00", "function": "0x0"}))
        pci = "<hostdev mode='subsystem' type='pci' managed='yes'><source><address domain='0x0000' bus='0x05' slot='0x00' function='0x0'/></source></hostdev>"
        proxy = vm("", domain(pci), active=False)
        proxy.delete_pci_hostdev("0000:05:00.0")
        self.assertEqual(proxy.instance.detachDeviceFlags.call_args.args[1], libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        with self.assertRaisesRegex(OperationError, "no PCI device 0000:06:00.0"):
            proxy.delete_pci_hostdev("0000:06:00.0")
        running = vm(domain(pci), domain(pci))
        for change in (running.add_pci_hostdev, running.delete_pci_hostdev):
            with self.assertRaisesRegex(OperationError, "Shut the VM down"):
                change("0000:05:00.0")
        running.instance.attachDeviceFlags.assert_not_called()
        running.instance.detachDeviceFlags.assert_not_called()
        # a saved state would start the VM without the change
        saved = vm("", domain(pci), active=False)
        saved.instance.hasManagedSaveImage.return_value = 1
        with self.assertRaisesRegex(OperationError, "without a saved state"):
            saved.add_pci_hostdev("0000:06:00.0")

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


class MigrationTests(unittest.TestCase):
    def test_a_vm_with_host_devices_is_not_migrated(self):
        for devices, state in ((by_model(), 1), (by_model(), 5), ("<hostdev mode='subsystem' type='pci'/>", 1)):
            source = FakeSource(state, xml=with_disks(devices))
            with self.subTest(state=state), self.assertRaisesRegex(OperationError, "host devices cannot be migrated"):
                destination().moveto(source, "vm", live=state == 1, unsafe=False, offline=state == 5)
            self.assertEqual(source.instance.calls, [])


class HostUsbViewTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="hd", hostname="192.0.2.31", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=self.compute, name="kiosk-1", uuid="00000000-0000-4000-8000-0000000000e1")
        self.client.force_login(get_user_model().objects.create_superuser("hd", "hd@example.com", "pw"))
        patcher = patch("instances.models.wvmInstance")
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)
        # the host of the node device fixture; another VM holds tablet 1/3 by address
        other = MagicMock(**{"name.return_value": "db-1", "isPersistent.return_value": False,
                             "XMLDesc.return_value": domain(by_model("<address bus='1' device='3'/>"))})
        self.proxy.wvm.listAllDevices.return_value = [node(*n) for n in NODES]
        self.proxy.domain_trees.side_effect = lambda: [("db-1", [etree.fromstring(other.XMLDesc())])]
        self.proxy.get_hostdevs.return_value = ([], [], [])

    def test_the_form_offers_what_can_be_given_and_says_why_not(self):
        page = html.fromstring(self.client.get(reverse("instances:host_devices", args=[self.instance.id])).content)
        options = {o.get("value"): (o.get("disabled") is not None, o.text_content()) for o in page.xpath("//select[@name='usb_device']/option[@value!='']")}
        self.assertEqual(sorted(options), ["1/1", "1/2", "1/3"])
        self.assertTrue(options["1/1"][0] and "is a hub" in options["1/1"][1])
        self.assertTrue(options["1/3"][0] and "is given to db-1" in options["1/3"][1])
        self.assertFalse(options["1/2"][0])
        # a device the VM has already
        self.proxy.domain_trees.side_effect = lambda: [("kiosk-1", [etree.fromstring(domain(by_model("<address bus='1' device='2'/>")))])]
        page = html.fromstring(self.client.get(reverse("instances:host_devices", args=[self.instance.id])).content)
        self.assertEqual(page.xpath("//option[@value='1/2']/@disabled"), ["disabled"])

    def test_a_device_is_given_by_address_when_the_host_has_several_of_its_model(self):
        url = reverse("instances:add_usb_hostdev", args=[self.instance.id])
        response = self.client.post(url, {"usb_device": "1/2"})
        self.assertEqual(response.status_code, 302)
        self.proxy.add_usb_hostdev.assert_called_once_with("0x0627", "0x0001", (1, 2))
        # refused on the server too: another VM's device, a hub
        for chosen, why in (("1/3", "is given to db-1"), ("1/1", "is a hub"), ("9/9", "has no USB device")):
            response = self.client.post(url, {"usb_device": chosen})
            with self.subTest(chosen=chosen):
                self.assertIn(why, " ".join(str(m) for m in get_messages(response.wsgi_request)))
        self.assertEqual(self.proxy.add_usb_hostdev.call_count, 1)

    def test_a_device_is_given_by_model_when_the_host_has_one_of_it(self):
        self.proxy.wvm.listAllDevices.return_value = [node(*n) for n in NODES if n[0] not in ("usb_1_2", "usb_1_2_1_0")]
        self.client.post(reverse("instances:add_usb_hostdev", args=[self.instance.id]), {"usb_device": "1/2"})
        self.proxy.add_usb_hostdev.assert_called_once_with("0x0627", "0x0001", None)

    def test_a_pci_device_is_given_when_it_can_be(self):
        url = reverse("instances:add_pci_hostdev", args=[self.instance.id])
        # the host's own NIC: refused with the reason
        response = self.client.post(url, {"pci_device": "0000:00:06.0"})
        self.assertIn("holds the host's eth0", " ".join(str(m) for m in get_messages(response.wsgi_request)))
        self.proxy.add_pci_hostdev.assert_not_called()
        self.client.post(url, {"pci_device": "0000:00:0a.0"})  # bound to vfio-pci, alone in its group
        self.proxy.add_pci_hostdev.assert_called_once_with("0000:00:0a.0")
        self.client.post(reverse("instances:delete_pci_hostdev", args=[self.instance.id]), {"address": "0000:00:0a.0"})
        self.proxy.delete_pci_hostdev.assert_called_once_with("0000:00:0a.0")

    def test_the_pci_form_waits_for_a_shut_off_vm(self):
        self.proxy.instance.isActive.return_value = True
        page = html.fromstring(self.client.get(reverse("instances:host_devices", args=[self.instance.id])).content)
        self.assertEqual(page.xpath("//select[@name='pci_device']/@disabled"), ["disabled"])
        self.assertIn("Shut the VM down", page.text_content())

    def test_a_device_is_taken_back_by_its_selector(self):
        url = reverse("instances:delete_usb_hostdev", args=[self.instance.id])
        self.client.post(url, {"vendor": "0x0627", "product": "0x0001", "address": ""})
        self.client.post(url, {"vendor": "0x0627", "product": "0x0001", "address": "1/3"})
        self.assertEqual([c.args[0] for c in self.proxy.delete_usb_hostdev.call_args_list],
                         [("0x0627", "0x0001", None), ("0x0627", "0x0001", (1, 3))])

    def test_only_superusers(self):
        self.client.force_login(get_user_model().objects.create_user("hd-user", "u@example.com", "pw"))
        self.assertEqual(self.client.get(reverse("instances:host_devices", args=[self.instance.id])).status_code, 403)
        self.client.post(reverse("instances:add_usb_hostdev", args=[self.instance.id]), {"usb_device": "1/2"})
        self.client.post(reverse("instances:add_pci_hostdev", args=[self.instance.id]), {"pci_device": "0000:00:0a.0"})
        self.client.post(reverse("instances:delete_pci_hostdev", args=[self.instance.id]), {"address": "0000:00:0a.0"})
        self.proxy.add_usb_hostdev.assert_not_called()
        self.proxy.add_pci_hostdev.assert_not_called()
        self.proxy.delete_pci_hostdev.assert_not_called()


class RevertTests(TestCase):
    """A revert gives the VM the host devices of the snapshot, as it ran and
    as saved: not one another VM names; and it holds the compute meanwhile."""

    def setUp(self):
        from instances.jobs import RevertSnapshot

        self.kind = RevertSnapshot()
        compute = Compute.objects.create(name="rv", hostname="192.0.2.32", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="kiosk-1", uuid="00000000-0000-4000-8000-0000000000e2")
        patcher = patch("instances.jobs.wvmInstance")
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.proxy.instance.name.return_value = "kiosk-1"
        self.proxy.wvm.listAllDevices.return_value = [node(*n) for n in NODES]
        self.proxy.domain_trees.side_effect = lambda: [("db-1", [etree.fromstring(domain(by_model("<address bus='1' device='3'/>")))])]
        self.params = {"instance": self.instance.id, "name": "s1", "external": False}

    def snapshot(self, running, saved=None):
        saved = f"<inactiveDomain><devices>{saved}</devices></inactiveDomain>" if saved is not None else ""
        self.proxy._snapshot.return_value.getXMLDesc.return_value = \
            f"<domainsnapshot><domain><devices>{running}</devices></domain>{saved}</domainsnapshot>"

    def precheck(self):
        op = MagicMock(params=self.params, intent={"compute": self.instance.compute_id}, user=MagicMock(is_superuser=True))
        with patch("instances.jobs._authorized", return_value=self.instance):
            self.kind.precheck(op, None)

    def test_a_device_another_vm_names_is_not_given_back(self):
        for running, saved in ((by_model(), None), ("", by_model())):  # the saved definition counts too
            self.snapshot(running, saved)
            with self.subTest(saved=saved), self.assertRaisesRegex(OperationError, "is given to db-1"):
                self.precheck()

    def test_the_compute_is_held_only_for_a_revert_with_host_devices(self):
        compute = f"compute:{self.instance.compute_id}"
        self.snapshot(by_model())
        self.assertEqual(self.kind.plan(None, self.params).claims[compute], "exclusive")
        self.snapshot("")
        self.assertEqual(self.kind.plan(None, self.params).claims[compute], "shared")
        self.precheck()  # no host device: the host's devices are not read
        self.proxy.wvm.listAllDevices.assert_not_called()
