"""A VM's console is its first graphics device: each setting is read from
it, and a switch away from SPICE leaves a definition libvirt accepts."""

import unittest

from lxml import etree

from vrtManager.instance import wvmInstance

SPICE = """<domain><devices>
    <graphics type='spice' autoport='yes' keymap='de' passwd='%s'><listen type='address' address='0.0.0.0'/></graphics>
    <channel type='spicevmc'><target type='virtio' name='com.redhat.spice.0'/></channel>
    <channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>
    <redirdev bus='usb' type='spicevmc'/><smartcard mode='passthrough' type='spicevmc'/>
    <audio id='1' type='spice'/><video><model type='qxl'/></video></devices></domain>"""


def vm(xml):
    p = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    p._XMLDesc = lambda flags: xml
    p.defined = []
    p._defineXML = p.defined.append
    return p


class ConsoleGraphicsTestCase(unittest.TestCase):
    def test_a_switch_from_spice_drops_the_devices_that_need_it(self):
        for console_type in ("vnc", "pty"):
            with self.subTest(console_type):
                p = vm(SPICE % "spice123")
                p.set_console_type(console_type)
                devices = etree.fromstring(p.defined[0]).find("devices")
                self.assertEqual([c.get("type") for c in devices.findall("channel")], ["unix"])
                self.assertEqual(devices.findall("redirdev") + devices.findall("smartcard"), [])
                self.assertEqual(devices.find("audio").get("type"), "none")
                self.assertEqual(devices.find("video/model").get("type"), "qxl")

    def test_vnc_keeps_the_spice_keymap_and_a_password_it_can_take(self):
        for passwd, kept in (("spice123", True), ("a-longer-spice-password", False)):
            with self.subTest(passwd):
                p = vm(SPICE % passwd)
                p.set_console_type("vnc")
                (graphic,) = etree.fromstring(p.defined[0]).findall("devices/graphics")
                self.assertEqual((graphic.get("type"), graphic.get("listen"), graphic.get("keymap")),
                                 ("vnc", "127.0.0.1", "de"))
                self.assertEqual(graphic.get("passwd") == passwd, kept)
                self.assertEqual(len(graphic.get("passwd")), 8)

    def test_every_setting_is_read_from_the_first_graphics_device(self):
        # VNC without a password or keymap first: SPICE's must not be shown as its
        p = vm("""<domain><devices><graphics type='vnc' port='5901'><listen type='address' address='127.0.0.1'/></graphics>
            <graphics type='spice' port='5902' passwd='spice123' keymap='de'>
            <listen type='address' address='0.0.0.0'/></graphics></devices></domain>""")
        self.assertEqual((p.get_console_type(), p.get_console_port(), p.get_console_passwd(),
                          p.get_console_keymap(), p.get_console_listener_addr()),
                         ("vnc", "5901", None, "", "127.0.0.1"))
