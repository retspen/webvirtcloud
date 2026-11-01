"""Live checks that each domain edit does what it says and nothing else.

For every edit the persistent definition (inactive, with secrets) is read
before and after. The edit must show its effect, and once the nodes it is
allowed to touch are removed from both sides, the rest of the definition
must be identical: unknown elements, secrets and pending changes survive.
On a running VM, edits of the persistent definition must leave the live
one alone. Runs only with TEST_LIBVIRT_HOST set (see instances/tests/livetest.py).
"""

import os
import unittest

import libvirt
from django.test import SimpleTestCase
from lxml import etree
from vrtManager.connection import connection_manager
from vrtManager.instance import wvmInstance

from . import livetest

P = livetest.PREFIX
MAC = "52:54:00:aa:02:01"
PERSISTENT = libvirt.VIR_DOMAIN_XML_INACTIVE | libvirt.VIR_DOMAIN_XML_SECURE
PARSER = etree.XMLParser(remove_blank_text=True)


def domain_xml(name, disk, iso):
    """A VM with elements WebVirtCloud does not manage, which edits must keep."""
    return f"""
<domain type='kvm'>
  <name>{name}</name>
  <title>original title</title>
  <metadata><app:info xmlns:app='http://example.com/wvc-test'>keep-metadata</app:info></metadata>
  <memory unit='MiB'>128</memory>
  <currentMemory unit='MiB'>128</currentMemory>
  <memoryBacking><nosharepages/></memoryBacking>
  <vcpu placement='static'>1</vcpu>
  <cputune><shares>2048</shares></cputune>
  <os><type arch='x86_64' machine='q35'>hvm</type><boot dev='hd'/></os>
  <features><acpi/><apic/></features>
  <on_crash>restart</on_crash>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='none'/>
      <source file='{disk}'/>
      <target dev='vda' bus='virtio'/>
      <serial>keep-serial</serial>
      <iotune><total_bytes_sec>10485760</total_bytes_sec></iotune>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      <source file='{iso}'/>
      <target dev='sda' bus='sata'/>
      <readonly/>
    </disk>
    <interface type='network'>
      <mac address='{MAC}'/>
      <source network='default'/>
      <model type='virtio'/>
      <bandwidth><outbound average='1000' peak='2000' burst='1024'/></bandwidth>
    </interface>
    <graphics type='vnc' autoport='yes' passwd='keep1234' keymap='en-us'>
      <listen type='address' address='0.0.0.0'/>
    </graphics>
    <video><model type='vga' primary='yes'/></video>
    <serial type='pty'><target port='0'/></serial>
    <rng model='virtio'><backend model='random'>/dev/urandom</backend></rng>
    <watchdog model='i6300esb' action='reset'/>
    <controller type='virtio-serial'/>  <!-- add_guest_agent hotplugs a channel -->
  </devices>
</domain>"""


def first(tree, path):
    found = tree.xpath(path)
    return found[0] if found else None


# name -> (edit, check of the new persistent tree, paths the edit may change,
#          allowed while running, changes the running VM too)
EDITS = {
    "set_bootmenu": (
        lambda vm: vm.set_bootmenu(1),
        lambda t: first(t, "os/bootmenu/@enable") == "yes",
        ["os/bootmenu"], True, False,
    ),
    "set_bootorder": (
        lambda vm: vm.set_bootorder({0: {"type": "disk", "dev": "vda"}}),
        lambda t: first(t, "devices/disk[target/@dev='vda']/boot/@order") == "1" and not t.xpath("os/boot"),
        ["os/boot", "devices/*/boot"], True, False,
    ),
    "set_vcpu_hotplug": (
        lambda vm: vm.set_vcpu_hotplug(True, 1),
        lambda t: bool(t.xpath("vcpus/vcpu")),
        ["vcpus"], False, False,
    ),
    "set_console_keymap": (
        lambda vm: vm.set_console_keymap("de"),
        lambda t: first(t, "devices/graphics/@keymap") == "de",
        ["devices/graphics/@keymap"], True, False,
    ),
    "set_console_listener_addr": (
        lambda vm: vm.set_console_listener_addr("127.0.0.1"),
        lambda t: first(t, "devices/graphics/listen/@address") == "127.0.0.1",
        ["devices/graphics/@listen", "devices/graphics/listen/@address"], True, False,
    ),
    "set_console_type pty": (
        lambda vm: vm.set_console_type("pty"),
        lambda t: not t.xpath("devices/graphics") and first(t, "devices/console/@type") == "pty",
        ["devices/graphics", "devices/console"], True, False,
    ),
    "set_console_type vnc": (
        lambda vm: vm.set_console_type("vnc"),
        lambda t: t.xpath("devices/graphics/@type") == ["vnc"] and first(t, "devices/graphics/@listen") == "127.0.0.1",
        ["devices/graphics"], True, False,
    ),
    "set_console_passwd": (
        lambda vm: vm.set_console_passwd("new12345"),
        lambda t: first(t, "devices/graphics/@passwd") == "new12345",
        ["devices/graphics/@passwd"], True, False,
    ),
    "set_video_model": (
        lambda vm: vm.set_video_model("virtio"),
        lambda t: first(t, "devices/video/model/@type") == "virtio",
        ["devices/video"], True, False,
    ),
    "set_rng": (
        lambda vm: vm.set_rng(False),
        lambda t: not t.xpath("devices/rng"),
        ["devices/rng"], True, False,
    ),
    "set_tpm": (
        lambda vm: vm.set_tpm(True),
        lambda t: first(t, "devices/tpm/backend/@version") == "2.0",
        ["devices/tpm"], True, False,
    ),
    "set_on_crash": (
        lambda vm: vm.set_on_crash("restart"),
        lambda t: t.findtext("on_crash") == "restart",
        ["on_crash"], True, False,
    ),
    "resize_cpu": (
        lambda vm: vm.resize_cpu("1", "2"),
        lambda t: t.findtext("vcpu") == "2" and first(t, "vcpu/@current") == "1",
        ["vcpu"], True, False,
    ),
    "resize_mem": (
        lambda vm: vm.resize_mem(128, 160),
        lambda t: t.findtext("memory") == str(160 * 1024),
        ["memory", "currentMemory"], False, False,
    ),
    "set_options": (
        lambda vm: vm.set_options({"title": "new title", "description": "new description"}),
        lambda t: t.findtext("title") == "new title" and t.findtext("description") == "new description",
        ["title", "description"], True, False,
    ),
    "set_qos": (
        lambda vm: vm.set_qos(MAC, "inbound", 100, 200, 300),
        lambda t: first(t, "devices/interface/bandwidth/inbound/@average") == "100"
        and first(t, "devices/interface/bandwidth/outbound/@average") == "1000",
        ["devices/interface/bandwidth/inbound"], True, False,
    ),
    "unset_qos": (
        lambda vm: vm.unset_qos(MAC, "outbound"),
        lambda t: not t.xpath("devices/interface/bandwidth/outbound"),
        ["devices/interface/bandwidth"], True, False,
    ),
    "umount_iso": (
        lambda vm: vm.umount_iso("sda"),
        lambda t: not t.xpath("devices/disk[target/@dev='sda']/source/@file"),
        ["devices/disk[target/@dev='sda']/source"], True, True,
    ),
    "set_link_state": (
        lambda vm: vm.set_link_state(MAC, "down"),
        lambda t: first(t, "devices/interface/link/@state") == "down",
        ["devices/interface/link"], True, True,
    ),
    "change_network (same MAC, new model)": (
        lambda vm: vm.change_network(MAC, MAC, "default", "net", "e1000e", ""),
        lambda t: first(t, "devices/interface/model/@type") == "e1000e"
        and first(t, "devices/interface/bandwidth/outbound/@average") == "1000",
        ["devices/interface/model"], True, False,
    ),
    "add_network": (
        lambda vm: vm.add_network("52:54:00:aa:02:09", "default", "net", "virtio"),
        lambda t: len(t.xpath("devices/interface")) == 2,
        ["devices/interface[mac/@address='52:54:00:aa:02:09']"], True, True,
    ),
    "delete_network": (
        lambda vm: vm.delete_network(MAC),
        lambda t: not t.xpath("devices/interface"),
        ["devices/interface"], True, True,
    ),
    "attach_disk": (
        lambda vm: vm.attach_disk("vdc", livetest.create_volume(vm.wvm, P + "fx-extra"), target_bus="virtio", format_type="qcow2"),
        lambda t: bool(t.xpath("devices/disk[target/@dev='vdc']")),
        ["devices/disk[target/@dev='vdc']"], True, True,
    ),
    "add_guest_agent": (
        lambda vm: vm.add_guest_agent(),
        lambda t: bool(t.xpath("devices/channel/target[@name='org.qemu.guest_agent.0']")),
        ["devices/channel[target/@name='org.qemu.guest_agent.0']"], True, True,
    ),
    "edit_disk (cache mode)": (
        lambda vm: vm.edit_disk("vda", vm.get_disk_devices(config=True)[0]["path"], False, False, "virtio",
                                "keep-serial", "qcow2", "writeback", None, None, None),
        lambda t: first(t, "devices/disk[target/@dev='vda']/driver/@cache") == "writeback",
        ["devices/disk[target/@dev='vda']/driver/@cache"], True, False,
    ),
}


def canonical(tree, paths):
    tree = etree.fromstring(etree.tostring(tree), PARSER)
    for path in paths:
        for node in tree.xpath(path):
            if isinstance(node, etree._ElementUnicodeResult):
                node.getparent().attrib.pop(node.attrname, None)
            else:
                node.getparent().remove(node)
    return etree.tostring(tree, method="c14n").decode()


class LiveXmlEffectsTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        if not livetest.enabled():
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST to run the live libvirt tests")
        cls.args = (
            os.environ["TEST_LIBVIRT_HOST"],
            os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.args)
        livetest.cleanup(cls.conn)
        livetest.ensure_pool(cls.conn)
        cls.inventory = livetest.inventory(cls.conn)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            livetest.remove_pool(cls.conn)
        finally:
            super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")

    def vm(self, running, paused=False):
        disk = livetest.create_volume(self.conn, P + "fx")
        iso = self.conn.storagePoolLookupByName(livetest.POOL).createXML(
            f"<volume><name>{P}fx.iso</name><capacity unit='MiB'>1</capacity><target><format type='raw'/></target></volume>", 0
        ).path()
        dom = self.conn.defineXML(domain_xml(P + "fx", disk, iso))
        if running:
            dom.create()
            # A pending change only in the persistent definition
            tree = self.persistent(dom)
            tree.find("on_crash").text = "destroy"
            self.conn.defineXML(etree.tostring(tree).decode())
            if paused:
                dom.suspend()
        return dom, wvmInstance(*self.args, None, uuid=dom.UUIDString())

    def persistent(self, dom):
        return etree.fromstring(dom.XMLDesc(PERSISTENT), PARSER)

    def live(self, dom):
        return etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_SECURE), PARSER)

    def check(self, running, paused=False):
        for name, (edit, effect, touched, allowed_running, changes_live) in EDITS.items():
            if running and not allowed_running:
                continue
            with self.subTest(name):
                try:
                    dom, vm = self.vm(running, paused)
                    before, live_before = self.persistent(dom), dom.isActive() and self.live(dom)
                    edit(vm)
                    after = self.persistent(dom)
                    self.assertTrue(effect(after), "edit had no effect")
                    self.assertEqual(canonical(after, touched), canonical(before, touched), "unrelated change")
                    # An unplug completes only when the guest acknowledges it; these
                    # VMs have no OS (test_live_guest covers it with a real guest).
                    if running and changes_live and name != "delete_network":
                        self.assertTrue(effect(self.live(dom)), "edit did not reach the running VM")
                    if running and not changes_live:
                        self.assertEqual(
                            canonical(self.live(dom), ["devices/graphics/@port"]),
                            canonical(live_before, ["devices/graphics/@port"]),
                            "persistent-only edit changed the running VM",
                        )
                finally:
                    livetest.cleanup(self.conn)

    def test_edits_of_a_stopped_vm(self):
        self.check(running=False)

    def test_edits_of_a_running_vm(self):
        self.check(running=True)

    def test_edits_of_a_paused_vm(self):
        self.check(running=True, paused=True)

    def test_enabling_vcpu_hotplug_keeps_the_current_vcpus(self):
        try:
            dom, vm = self.vm(running=False)
            vm.resize_cpu("2", "4")
            vm.set_vcpu_hotplug(True)
            after = self.persistent(dom)
            self.assertEqual((after.findtext("vcpu"), first(after, "vcpu/@current")), ("4", "2"))
            self.assertEqual(after.xpath("vcpus/vcpu/@enabled"), ["yes", "yes", "no", "no"])
            self.assertEqual(after.xpath("vcpus/vcpu/@hotpluggable"), ["no", "yes", "yes", "yes"])
            dom.create()
            self.assertEqual(dom.vcpusFlags(libvirt.VIR_DOMAIN_AFFECT_LIVE), 2)
        finally:
            livetest.cleanup(self.conn)
