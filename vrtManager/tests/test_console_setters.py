import unittest
from unittest.mock import MagicMock

from lxml import etree
from vrtManager.instance import PERSISTENT_XML, wvmInstance
from django.test import TestCase

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


class ConsoleListensLocallyTests(TestCase):
    """Only a binding the persistent XML pins to loopback (or a Unix socket) is local."""

    def listens_locally(self, graphics):
        proxy = wvmInstance.__new__(wvmInstance)  # no connection: only the XML is read
        xml = f"<domain><devices>{graphics}</devices></domain>"
        proxy._XMLDesc = lambda flags: xml if flags == PERSISTENT_XML else "<wrong-flags/>"
        return proxy.console_listens_locally()

    def test_cases(self):
        cases = {
            "<graphics type='vnc' listen='127.0.0.1'><listen type='address' address='127.0.0.1'/></graphics>": True,
            "<graphics type='vnc'><listen type='address' address='::1'/></graphics>": True,
            "<graphics type='vnc'><listen type='socket' socket='/run/vnc.sock'/></graphics>": True,
            "": True,  # no console
            "<graphics type='vnc' listen='0.0.0.0'><listen type='address' address='0.0.0.0'/></graphics>": False,
            "<graphics type='vnc'><listen type='network' network='default'/></graphics>": False,
            "<graphics type='vnc' autoport='yes'/>": False,  # the host default decides
            "<graphics type='vnc'><listen type='address' address='localhost'/></graphics>": False,
            "<graphics type='vnc' listen='127.0.0.1'><listen type='address' address='10.0.0.5'/></graphics>": False,
        }
        for graphics, expected in cases.items():
            with self.subTest(graphics=graphics):
                self.assertIs(self.listens_locally(graphics), expected)
