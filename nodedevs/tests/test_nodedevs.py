"""The host's devices page: PCI devices by IOMMU group and USB devices, each
with what the host has on it (network interfaces, disks, its graphics card)
and the VMs that name it, by PCI address, by USB address or by USB model
only. Node device XML as libvirt 11.10 writes it; the connection is a mock,
libvirt's test driver has no node devices."""

from unittest.mock import MagicMock, patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from vrtManager.connection import wvmConnect
from vrtManager.nodedevs import node_devices, pci_address


def pci(slot, product, code, driver=None, group=None):
    iommu = f"<iommuGroup number='{group}'><address domain='0x0000' bus='0x00' slot='{slot}' function='0x0'/></iommuGroup>" \
        if group is not None else ""
    driver = f"<driver><name>{driver}</name></driver>" if driver else ""
    return (f"pci_0000_00_{int(slot, 16):02x}_0", f"""<device><name>pci_0000_00_{int(slot, 16):02x}_0</name><parent>computer</parent>{driver}
        <capability type='pci'><class>{code}</class><domain>0</domain><bus>0</bus><slot>{int(slot, 16)}</slot><function>0</function>
        <product id='0x1000'>{product}</product><vendor id='0x1af4'>Red Hat, Inc.</vendor>{iommu}</capability></device>""")


def child(name, parent, capability):
    return name, f"<device><name>{name}</name><parent>{parent}</parent>{capability}</device>"


def usb(name, parent, bus, device, product="QEMU Tablet", vendor_id="0x0627", product_id="0x0001"):
    return name, f"""<device><name>{name}</name><parent>{parent}</parent><capability type='usb_device'><bus>{bus}</bus>
        <device>{device}</device><product id='{product_id}'>{product}</product><vendor id='{vendor_id}'>Adomax</vendor>
        </capability></device>"""


def interface(name, parent, code):
    return child(name, parent, f"<capability type='usb'><number>0</number><class>{code}</class></capability>")


NODES = [
    pci("0x06", "Virtio network device", "0x020000", "virtio-pci", group=3),
    child("net_eth0", "pci_0000_00_06_0", "<capability type='net'><interface>eth0</interface></capability>"),
    pci("0x03", "Virtio block device", "0x010000", "virtio-pci", group=2),
    child("virtio1", "pci_0000_00_03_0", "<capability type='system'/>"),  # a level between, not a resource
    child("block_vda", "virtio1", "<capability type='storage'><block>/dev/vda</block></capability>"),
    pci("0x02", "Virtio 1.0 GPU", "0x030000", "virtio-pci", group=2),
    child("drm_card0", "pci_0000_00_02_0", "<devnode type='dev'>/dev/dri/card0</devnode><capability type='drm'><type>primary</type></capability>"),
    child("drm_render", "pci_0000_00_02_0", "<devnode type='dev'>/dev/dri/renderD128</devnode><capability type='drm'><type>render</type></capability>"),
    pci("0x0a", "Ethernet controller", "0x020000", "vfio-pci", group=4),
    pci("0x01", "PIIX3 USB", "0x0c0300", "uhci_hcd"),
    usb("usb_usb1", "pci_0000_00_01_0", 1, 1, "1.1 root hub", "0x1d6b", "0x0001"),
    interface("usb_1_0_1_0", "usb_usb1", 9),
    usb("usb_1_1", "usb_usb1", 1, 2),
    interface("usb_1_1_1_0", "usb_1_1", 3),
    usb("usb_1_2", "usb_usb1", 1, 3),
    interface("usb_1_2_1_0", "usb_1_2", 3),
]


def node(name, xml):
    return MagicMock(**{"name.return_value": name, "XMLDesc.return_value": xml})


def vm(name, hostdevs, saved=None):
    """A VM with hostdevs as it runs and, given saved, persistent with those for its next start."""
    def describe(flags=0):
        return f"<domain><devices>{saved if flags else hostdevs}</devices></domain>"
    return MagicMock(**{"name.return_value": name, "XMLDesc.side_effect": describe, "isPersistent.return_value": saved is not None})


PCI_0A = "<hostdev mode='subsystem' type='pci'><source><address domain='0x0000' bus='0x00' slot='0x0a' function='0x0'/></source></hostdev>"
USB_1_3 = "<hostdev mode='subsystem' type='usb'><source><vendor id='0x0627'/><product id='0x0001'/><address bus='1' device='3'/></source></hostdev>"
USB_MODEL = "<hostdev mode='subsystem' type='usb'><source><vendor id='0x0627'/><product id='0x0001'/></source></hostdev>"


def devices(nodes=NODES, domains=()):
    conn = wvmConnect.__new__(wvmConnect)
    conn.wvm = MagicMock(**{"listAllDevices.return_value": [node(*n) for n in nodes],
                            "listAllDomains.return_value": list(domains)})
    return node_devices(conn)


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


class NodeDevicesPageTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="nd", hostname="192.0.2.30", login="root", password="", type=1)
        self.client.force_login(get_user_model().objects.create_superuser("nd", "nd@example.com", "pw"))
        self.url = reverse("nodedevs", args=[self.compute.id])

    def page(self, nodes=NODES, domains=()):
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            get.return_value.listAllDevices.return_value = [node(*n) for n in nodes]
            get.return_value.listAllDomains.return_value = list(domains)
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def test_the_page_groups_pci_devices_and_links_their_vms(self):
        instance = Instance.objects.create(compute=self.compute, name="db-1", uuid="00000000-0000-4000-8000-0000000000d1")
        page = self.page(domains=[vm("db-1", PCI_0A), vm("outside-1", USB_1_3)])
        headers = [" ".join(h.text_content().split()) for h in page.xpath("//tr[@data-group-header]")]
        self.assertEqual(headers, ["IOMMU group 2", "IOMMU group 3", "IOMMU group 4", "Without an IOMMU group"])
        self.assertEqual(page.xpath("//a[text()='db-1']/@href"), [reverse("instances:instance", args=[instance.id])])
        self.assertIn("outside-1", page.text_content())  # a VM the panel does not have: named, not linked
        self.assertNotIn("No IOMMU groups detected", page.text_content())

    def test_a_host_without_iommu_groups_says_so(self):
        page = self.page(nodes=[n for n in NODES if "iommuGroup" not in n[1]])
        self.assertIn("No IOMMU groups detected", page.text_content())

    def test_a_host_without_pci_or_usb_devices_says_so(self):
        page = self.page(nodes=[n for n in NODES if "usb" in n[0]])
        self.assertIn("The host reports no PCI devices.", page.text_content())
        self.assertNotIn("No IOMMU groups detected", page.text_content())  # nothing to give
        self.assertIn("The host reports no USB devices.", self.page(nodes=NODES[:2]).text_content())

    def test_only_superusers(self):
        self.client.force_login(get_user_model().objects.create_user("nd-user", "u@example.com", "pw"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_a_host_not_read_shows_no_device(self):
        # without the VMs' definitions a device would look free
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            get.return_value.listAllDevices.return_value = [node(*n) for n in NODES]
            get.return_value.listAllDomains.side_effect = libvirt.libvirtError("unreachable")
            response = self.client.get(self.url)
        page = html.fromstring(response.content)
        self.assertEqual(page.xpath("//table"), [])
        self.assertIn("unreachable", page.text_content())
