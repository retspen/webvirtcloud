import unittest
from unittest.mock import MagicMock

from lxml import etree
from vrtManager.instance import PERSISTENT_XML, wvmInstance

LIVE = "<domain><devices><graphics type='vnc' passwd='live' keymap='en-us'><listen type='address'/></graphics></devices></domain>"
PERSISTENT = "<domain><devices><graphics type='vnc' passwd='old'><listen type='address'/></graphics></devices></domain>"


def running_vm_with_pending_changes():
    vm = wvmInstance.__new__(wvmInstance)
    vm.wvm = MagicMock()
    vm._XMLDesc = MagicMock(side_effect=lambda flags: PERSISTENT if flags == PERSISTENT_XML else LIVE)
    return vm


class ConsoleSettersTestCase(unittest.TestCase):
    """The graphics device to edit comes from the persistent definition."""

    def defined_graphics(self, vm):
        return etree.fromstring(vm.wvm.defineXML.call_args[0][0]).find("devices/graphics")

    def test_setters_edit_the_persistent_graphics_device(self):
        edits = {
            "set_console_passwd": (lambda vm: vm.set_console_passwd("new"), "passwd", "new"),
            "set_console_keymap": (lambda vm: vm.set_console_keymap("de"), "keymap", "de"),
            "set_console_listener_addr": (lambda vm: vm.set_console_listener_addr("127.0.0.1"), "listen", "127.0.0.1"),
        }
        for name, (edit, attr, value) in edits.items():
            with self.subTest(name):
                vm = running_vm_with_pending_changes()
                edit(vm)
                graphics = self.defined_graphics(vm)
                self.assertEqual(graphics.get(attr), value)
                # Built from the persistent device, not the live one
                self.assertNotEqual(graphics.get("passwd"), "live")


if __name__ == "__main__":
    unittest.main()
