import unittest
from unittest.mock import MagicMock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager.instance import PERSISTENT_XML, wvmInstance

DOMAIN = """<domain><name>vm</name><memory>131072</memory><currentMemory>131072</currentMemory>
<vcpu>1</vcpu><os><type>hvm</type></os><devices>
<interface type='network'><mac address='52:54:00:00:00:01'/><source network='default'/></interface>
<graphics type='vnc' passwd='secret'><listen type='address' address='0.0.0.0'/></graphics>
<video><model type='vga' primary='yes'/></video></devices></domain>"""


class PersistentEditsTestCase(unittest.TestCase):
    """Edits read the persistent definition with secrets."""

    def test_edits_read_the_persistent_secure_definition(self):
        edits = {
            "set_bootmenu": lambda vm: vm.set_bootmenu(1),
            "set_console_keymap": lambda vm: vm.set_console_keymap("de"),
            "set_video_model": lambda vm: vm.set_video_model("virtio"),
            "resize_cpu": lambda vm: vm.resize_cpu("1", "2"),
            "set_options": lambda vm: vm.set_options({"title": "t"}),
            "set_qos": lambda vm: vm.set_qos("52:54:00:00:00:01", "inbound", 1, 2, 3),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                vm = wvmInstance.__new__(wvmInstance)
                vm.instance = MagicMock()
                vm.wvm = MagicMock()
                vm._XMLDesc = MagicMock(return_value=DOMAIN)
                vm.get_vcpus = MagicMock(return_value=None)
                vm.get_status = MagicMock(return_value=5)
                edit(vm)
                flags = {call.args[0] for call in vm._XMLDesc.call_args_list}
                self.assertIn(PERSISTENT_XML, flags)
                defined = (vm.wvm.defineXML.call_args or vm._XMLDesc.call_args)[0][0]
                self.assertIn("secret", str(defined))


class XmlFidelityTestCase(unittest.TestCase):
    def test_edits_keep_metadata_namespace_prefixes(self):
        xml = (
            "<domain><metadata><app:info xmlns:app='http://example.com/x'>v</app:info></metadata>"
            "<os><type>hvm</type></os><devices><graphics type='vnc'><listen type='address'/></graphics>"
            "<disk type='file' device='disk'><target dev='vda'/></disk></devices></domain>"
        )
        edits = {
            "set_bootmenu": lambda vm: vm.set_bootmenu(1),
            "set_bootorder": lambda vm: vm.set_bootorder({0: {"type": "disk", "dev": "vda"}}),
            "set_console_keymap": lambda vm: vm.set_console_keymap("de"),
            "set_console_passwd": lambda vm: vm.set_console_passwd("x"),
            "set_console_listener_addr": lambda vm: vm.set_console_listener_addr("127.0.0.1"),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                vm = wvmInstance.__new__(wvmInstance)
                vm.wvm = MagicMock()
                vm._XMLDesc = MagicMock(return_value=xml)
                edit(vm)
                self.assertIn("<app:info", vm.wvm.defineXML.call_args[0][0])


AGENT_DOMAIN = """<domain><name>vm</name><devices><channel type='unix'>
<target type='virtio' name='org.qemu.guest_agent.0'/></channel></devices></domain>"""


class DeviceEditsByStateTestCase(unittest.TestCase):
    """Disk, NIC and agent channel changes reach the running definition
    whenever the VM is active, paused included, and the persistent one
    always. An attach is one call for both; a removal is one per definition,
    from that definition's own XML."""

    EDITS = {
        "attach_disk": ("attachDeviceFlags", lambda vm: vm.attach_disk("vdb", "/var/lib/libvirt/images/d.qcow2")),
        "add_network": ("attachDeviceFlags", lambda vm: vm.add_network("52:54:00:00:00:09", "default")),
        "add_guest_agent": ("attachDeviceFlags", lambda vm: vm.add_guest_agent()),
        "remove_guest_agent": ("detachDeviceFlags", lambda vm: vm.remove_guest_agent()),
    }
    ATTACHES = ("attach_disk", "add_network", "add_guest_agent")

    def affected(self, state, active):
        from libvirt import VIR_DOMAIN_AFFECT_CONFIG, VIR_DOMAIN_AFFECT_LIVE

        names = {VIR_DOMAIN_AFFECT_LIVE: "live", VIR_DOMAIN_AFFECT_CONFIG: "config",
                 VIR_DOMAIN_AFFECT_LIVE | VIR_DOMAIN_AFFECT_CONFIG: "live+config"}
        result = {}
        for name, (method, edit) in self.EDITS.items():
            vm = wvmInstance.__new__(wvmInstance)
            vm.instance = MagicMock()
            vm.instance.isActive.return_value = active
            vm.get_status = MagicMock(return_value=state)
            # an agent channel is added where there is none, removed where there is one
            vm._XMLDesc = MagicMock(return_value=DOMAIN if name == "add_guest_agent" else AGENT_DOMAIN)
            edit(vm)
            result[name] = [names[c.args[1]] for c in getattr(vm.instance, method).call_args_list]
        return result

    def test_paused_vm(self):
        for name, affected in self.affected(state=3, active=True).items():
            self.assertEqual(affected, ["live+config"] if name in self.ATTACHES else ["live", "config"], name)

    def test_running_vm(self):
        for name, affected in self.affected(state=1, active=True).items():
            self.assertEqual(affected, ["live+config"] if name in self.ATTACHES else ["live", "config"], name)

    def test_stopped_vm(self):
        for name, affected in self.affected(state=5, active=False).items():
            self.assertEqual(affected, ["config"], name)

    def test_a_refused_attach_is_not_tried_again(self):
        from libvirt import libvirtError

        for name in self.ATTACHES:
            with self.subTest(name):
                vm = wvmInstance.__new__(wvmInstance)
                vm.instance = MagicMock()
                vm.instance.isActive.return_value = True
                vm._XMLDesc = MagicMock(return_value=DOMAIN)
                vm.instance.attachDeviceFlags.side_effect = libvirtError("target sda already exists")
                with self.assertRaises(libvirtError):
                    self.EDITS[name][1](vm)
                vm.instance.attachDeviceFlags.assert_called_once()

    def test_an_agent_channel_is_added_only_where_it_is_missing(self):
        from libvirt import VIR_DOMAIN_AFFECT_CONFIG, VIR_DOMAIN_AFFECT_LIVE

        for live, persistent, affected in ((AGENT_DOMAIN, AGENT_DOMAIN, []),
                                           (DOMAIN, AGENT_DOMAIN, [VIR_DOMAIN_AFFECT_LIVE]),
                                           (AGENT_DOMAIN, DOMAIN, [VIR_DOMAIN_AFFECT_CONFIG])):
            with self.subTest(affected=affected):
                vm = wvmInstance.__new__(wvmInstance)
                vm.instance = MagicMock(**{"isActive.return_value": True})
                vm._XMLDesc = lambda flags, live=live, persistent=persistent: persistent if flags == PERSISTENT_XML else live
                vm.add_guest_agent()
                self.assertEqual([c.args[1] for c in vm.instance.attachDeviceFlags.call_args_list], affected)


if __name__ == "__main__":
    unittest.main()
