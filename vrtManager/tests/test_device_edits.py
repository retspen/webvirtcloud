"""Device edits of a VM: each definition is changed as it describes the
device, every NIC type can be a boot device, posted values stay values, and
definition changes go through _defineXML, a QoS edit keeps the floor, and what the edit forms show is read from either definition. A boot order with a
missing device changes nothing. An active VM's memory is resized
by balloon, a stopped one's in its definition. Enabling vCPU hot plug keeps
the vCPUs enabled at boot."""

import unittest
from unittest.mock import MagicMock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from lxml import etree

from vrtManager import util
from vrtManager.instance import PERSISTENT_XML, wvmInstance
from libvirt import VIR_DOMAIN_AFFECT_CONFIG, VIR_DOMAIN_AFFECT_LIVE

PERSISTENT = """<domain><title>pending</title><vcpu current='2'>4</vcpu><os><type>hvm</type><bootmenu enable='yes'/></os><devices>
<disk type='file' device='disk'><source file='/pool/a.qcow2'/><target dev='vda' bus='virtio'/></disk>
<disk type='file' device='disk'><source file='/pool/b.qcow2'/><target dev='vdb' bus='virtio'/></disk>
<interface type='bridge'><mac address='52:54:10:00:00:02'/><source bridge='br0'/></interface>
<interface type='network'><mac address='52:54:10:00:00:01'/><source network='default'/>
<bandwidth><inbound average='1' peak='2' burst='3' floor='4'/></bandwidth></interface>
<disk type='file' device='cdrom'><target dev='sda' bus='sata'/><boot order='1'/></disk>
<video><model type='vga'/></video>
<graphics type='vnc' passwd='pending' keymap='de'><listen type='address' address='0.0.0.0'/></graphics>
</devices></domain>"""
LIVE = """<domain><vcpu>1</vcpu><os><type>hvm</type></os><devices>
<disk type='file' device='disk'><source file='/pool/a.qcow2'/><target dev='vda' bus='virtio'/><alias name='virtio-disk0'/></disk>
</devices></domain>"""


def proxy(active=True):
    p = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    p.instance = MagicMock(**{"isActive.return_value": active})
    p._XMLDesc = lambda flags: PERSISTENT if flags == PERSISTENT_XML else LIVE
    p._defineXML = MagicMock()
    p.wvm = MagicMock()
    return p


def defined(p):
    (xml,), _ = p._defineXML.call_args
    return etree.fromstring(xml)


class DetachDiskTestCase(unittest.TestCase):
    def test_each_definition_is_detached_as_it_describes_the_disk(self):
        p = proxy()
        p.detach_disk("vda")
        (live, live_flags), (config, config_flags) = (c.args for c in p.instance.detachDeviceFlags.call_args_list)
        self.assertEqual((live_flags, config_flags), (VIR_DOMAIN_AFFECT_LIVE, VIR_DOMAIN_AFFECT_CONFIG))
        self.assertIn("virtio-disk0", live)
        self.assertNotIn("alias", config)

    def test_a_disk_only_in_the_persistent_definition_is_detached_there(self):
        p = proxy()
        p.detach_disk("vdb")
        self.assertEqual([c.args[1] for c in p.instance.detachDeviceFlags.call_args_list], [VIR_DOMAIN_AFFECT_CONFIG])

    def test_an_unknown_disk_is_refused(self):
        p = proxy()
        with self.assertRaises(util.OperationError):
            p.detach_disk("vdz")
        p.instance.detachDeviceFlags.assert_not_called()


class VcpuHotplugTestCase(unittest.TestCase):
    def test_a_vcpu_turned_on_or_off_stays_so_at_the_next_start(self):
        p = proxy()
        p.set_vcpu("1", 1)
        p.instance.setVcpu.assert_called_once_with("1", 1, VIR_DOMAIN_AFFECT_LIVE | VIR_DOMAIN_AFFECT_CONFIG)

    def test_enabling_hotplug_keeps_the_current_vcpus_enabled(self):
        p = proxy(active=False)
        p.instance.info.return_value = [5]
        p._XMLDesc = lambda flags: "<domain><vcpu current='2'>4</vcpu></domain>"
        p.set_vcpu_hotplug(True)
        self.assertEqual(defined(p).xpath("vcpus/vcpu/@enabled"), ["yes", "yes"])


class DeviceEditsTestCase(unittest.TestCase):
    def test_a_block_volume_is_attached_by_its_device_path(self):
        p = proxy(active=False)
        p._definitions = lambda: [(PERSISTENT_XML, VIR_DOMAIN_AFFECT_CONFIG)]
        p.attach_disk("vdc", "/dev/vg/c", disk_type="block", target_bus="virtio")
        xml, _ = p.instance.attachDeviceFlags.call_args.args
        self.assertEqual(etree.fromstring(xml).find("source").attrib, {"dev": "/dev/vg/c"})

    def test_a_bridge_nic_can_be_a_boot_device(self):
        p = proxy()
        p.set_bootorder({0: {"type": "network", "dev": "52:54:10:00:00:02"}, 1: {"type": "disk", "dev": "vdb"}})
        tree = defined(p)
        self.assertEqual(tree.xpath("devices/interface[@type='bridge']/boot/@order"), ["1"])
        self.assertEqual(tree.xpath("devices/disk[target/@dev='vdb']/boot/@order"), ["2"])

    def test_the_video_model_is_a_value(self):
        p = proxy()
        p.set_video_model("vga' heads='9")
        model = defined(p).find("devices/video/model")
        self.assertEqual(model.attrib, {"type": "vga' heads='9"})
        p._defineXML.assert_called_once()

    def test_qos_changes_go_through_define_xml(self):
        for change in (
            lambda p: p.set_qos("52:54:10:00:00:01", "outbound", 1, 2, 3),
            lambda p: p.unset_qos("52:54:10:00:00:01", "inbound"),
        ):
            p = proxy()
            change(p)
            p._defineXML.assert_called_once()
            p.wvm.defineXML.assert_not_called()

    def test_a_qos_edit_keeps_the_floor(self):
        p = proxy()
        p.set_qos("52:54:10:00:00:01", "inbound", 10, 20, 30)
        inbound = defined(p).find("devices/interface[@type='network']/bandwidth/inbound")
        self.assertEqual(inbound.attrib, {"average": "10", "peak": "20", "burst": "30", "floor": "4"})

    def test_a_new_video_model_stays_the_primary_one(self):
        # the old model's memory sizes are its own: they go
        p = proxy()
        p._XMLDesc = lambda flags: PERSISTENT.replace("<model type='vga'/>", "<model type='vga' vram='16384' primary='yes'/>")
        p.set_video_model("virtio")
        self.assertEqual(defined(p).find("devices/video/model").attrib, {"type": "virtio", "primary": "yes"})

    def test_the_agent_channel_and_vcpu_hot_plug_are_read_from_either_definition(self):
        p = proxy()
        pending = ("<channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>"
                   "<video>")
        vcpus = "<vcpus><vcpu id='0' enabled='yes' hotpluggable='no'/><vcpu id='1' enabled='no' hotpluggable='yes'/></vcpus>"
        p._XMLDesc = lambda flags: (PERSISTENT.replace("<video>", pending).replace("<devices>", vcpus + "<devices>")
                                    if flags == PERSISTENT_XML else LIVE)
        self.assertEqual((p.get_guest_agent(), p.get_vcpus()), (None, {}))
        self.assertIsNotNone(p.get_guest_agent(config=True))
        self.assertEqual([v["hotpluggable"] for v in p.get_vcpus(config=True).values()], ["no", "yes"])

    def test_the_rng_device_is_the_panel_s_own_or_left_to_the_xml_editor(self):
        p = proxy()
        self.assertIsNone(p.get_rng())
        p.set_rng(True)
        self.assertEqual(etree.tostring(defined(p).find("devices/rng")).decode(),
                         "<rng model=\"virtio\"><backend model=\"random\">/dev/urandom</backend></rng>")
        added = etree.tostring(defined(p)).decode()
        p._XMLDesc = lambda flags: added
        self.assertEqual(p.get_rng(), "virtio")
        p.set_rng(False)
        self.assertIsNone(defined(p).find("devices/rng"))
        # the panel's device with the address libvirt gives it; another RNG device, or the panel's with
        # a rate or driver, is shown as custom and changed only in the XML editor
        backend = "<backend model='random'>{}</backend>"
        for inner, found in ((backend.format("/dev/urandom") + "<address type='pci' bus='0x08' slot='0x00'/>", "virtio"),
                             (backend.format("/dev/hwrng"), "custom"),
                             (backend.format("/dev/urandom") + "<rate bytes='1024' period='1000'/>", "custom"),
                             (backend.format("/dev/urandom") + "<driver iommu='on'/>", "custom")):
            with self.subTest(inner):
                p = proxy()
                p._XMLDesc = lambda flags, inner=inner: PERSISTENT.replace("<video>", f"<rng model='virtio'>{inner}</rng><video>")
                self.assertEqual(p.get_rng(), found)
                if found == "custom":
                    with self.assertRaises(util.OperationError):
                        p.set_rng(False)
                    p._defineXML.assert_not_called()

    def test_the_crash_action_is_restart_or_stop(self):
        p = proxy()
        self.assertEqual(p.get_on_crash(), "destroy")  # libvirt's default
        p.set_on_crash("restart")
        self.assertEqual(defined(p).findtext("on_crash"), "restart")
        with self.assertRaises(util.OperationError):
            p.set_on_crash("preserve")
        p._defineXML.assert_called_once()

    def test_cpu_title_and_description_are_read_from_either_definition(self):
        p = proxy()
        self.assertEqual((p.get_vcpu(), p.get_cur_vcpu(), p.get_title(), p.get_description()), (1, 1, "", ""))
        self.assertEqual((p.get_vcpu(config=True), p.get_cur_vcpu(config=True), p.get_title(config=True)), (4, 2, "pending"))

    def test_boot_video_and_console_are_read_from_either_definition(self):
        p = proxy()
        live = (p.get_bootmenu(), p.get_bootorder(), p.get_media_devices(), p.get_video_model(),
                p.get_console_listener_addr(), p.get_console_passwd(), p.get_console_keymap())
        self.assertEqual(live, (False, {}, [], None, "127.0.0.1", None, ""))
        self.assertEqual((p.get_bootmenu(config=True), p.get_bootorder(config=True), p.get_video_model(config=True)),
                         (True, {0: {"type": "file", "dev": "cdrom", "target": "sda"}}, "vga"))
        self.assertEqual([m["dev"] for m in p.get_media_devices(config=True)], ["sda"])
        self.assertEqual((p.get_console_listener_addr(config=True), p.get_console_passwd(config=True),
                          p.get_console_keymap(config=True)), ("0.0.0.0", "pending", "de"))

    def test_a_boot_order_with_a_device_not_in_the_definition_changes_nothing(self):
        p = proxy()
        for choice in ({"type": "disk", "dev": "vdz"}, {"type": "network", "dev": "52:54:10:00:00:99"},
                       {"type": "floppy", "dev": "fda"}):
            with self.subTest(choice), self.assertRaises(util.OperationError):
                p.set_bootorder({0: {"type": "disk", "dev": "vda"}, 1: choice})
        p._defineXML.assert_not_called()

    def test_a_boot_order_holding_a_device_the_list_does_not_show_is_not_replaced(self):
        for other in ("<hostdev mode='subsystem' type='pci'><boot order='2'/></hostdev>",
                      "<disk type='file' device='floppy'><target dev='fda'/><boot order='2'/></disk>"):
            with self.subTest(other):
                p = proxy()
                p._XMLDesc = lambda flags, other=other: PERSISTENT.replace("<video>", other + "<video>")
                with self.assertRaises(util.OperationError):
                    p.set_bootorder({0: {"type": "disk", "dev": "vda"}})
                p._defineXML.assert_not_called()

    def test_the_default_nic_model_leaves_the_choice_to_libvirt(self):
        p = proxy()
        p.change_network("52:54:10:00:00:01", "52:54:10:00:00:01", "default", "net", "default", "")
        self.assertIsNone(defined(p).find("devices/interface[@type='network']/model"))
        p = proxy(active=False)
        p.add_network("52:54:10:00:00:09", "default", model="default")
        xml, _ = p.instance.attachDeviceFlags.call_args.args
        self.assertIsNone(etree.fromstring(xml).find("model"))


class ResizeMemTestCase(unittest.TestCase):
    def test_an_active_vm_changes_only_its_current_memory(self):
        # a paused VM is active too: its guest applies the balloon once resumed
        p = proxy(active=True)
        p.resize_mem(96, 160)
        self.assertEqual(
            [c.args for c in p.instance.setMemoryFlags.call_args_list],
            [(96 * 1024, VIR_DOMAIN_AFFECT_LIVE), (96 * 1024, VIR_DOMAIN_AFFECT_CONFIG)],
        )
        p._defineXML.assert_not_called()

    def test_a_stopped_vm_gets_both_values_in_its_definition(self):
        p = proxy(active=False)
        p._XMLDesc = lambda flags: "<domain><memory>131072</memory><currentMemory>131072</currentMemory></domain>"
        p.resize_mem(96, 160)
        tree = defined(p)
        self.assertEqual((tree.findtext("memory"), tree.findtext("currentMemory")), (str(160 * 1024), str(96 * 1024)))
        p.instance.setMemoryFlags.assert_not_called()


if __name__ == "__main__":
    unittest.main()
