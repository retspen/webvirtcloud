import unittest
from unittest.mock import MagicMock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from libvirt import libvirtError
from vrtManager.instance import wvmInstance

DOMAIN_XML = """<domain><devices>
<interface type='network'><mac address='52:54:00:00:00:01'/><source network='default'/><model type='virtio'/></interface>
<interface type='network'><mac address='52:54:00:00:00:02'/><source network='default'/><model type='virtio'/>
<bandwidth><outbound average='1000'/></bandwidth><link state='down'/>
<address type='pci' domain='0x0000' bus='0x02' slot='0x00' function='0x0'/></interface>
<interface type='direct'><mac address='52:54:00:00:00:04'/><source dev='eth0' mode='vepa'/><model type='virtio'/></interface>
</devices></domain>"""


def stopped_instance():
    inst = wvmInstance.__new__(wvmInstance)
    inst.instance = MagicMock()
    inst.wvm = MagicMock()
    inst._XMLDesc = MagicMock(return_value=DOMAIN_XML)
    inst.get_status = MagicMock(return_value=5)
    return inst


class TestChangeNetwork(unittest.TestCase):
    def test_edits_the_nic_in_place_and_keeps_its_other_settings(self):
        from lxml import etree

        inst = stopped_instance()
        inst.change_network("52:54:00:00:00:02", "52:54:00:00:00:03", "br0", "bridge", "e1000", "clean-traffic")

        defined = etree.fromstring(inst.wvm.defineXML.call_args[0][0])
        first, second, _direct = defined.findall("devices/interface")
        self.assertEqual(first.find("mac").get("address"), "52:54:00:00:00:01")
        self.assertEqual(second.get("type"), "bridge")
        self.assertEqual(second.find("mac").get("address"), "52:54:00:00:00:03")
        self.assertEqual(second.find("source").attrib, {"bridge": "br0"})
        self.assertEqual(second.find("model").get("type"), "e1000")
        self.assertEqual(second.find("filterref").get("filter"), "clean-traffic")
        # QoS, link state and the PCI address survive
        self.assertEqual(second.find("bandwidth/outbound").get("average"), "1000")
        self.assertEqual(second.find("link").get("state"), "down")
        self.assertEqual(second.find("address").get("bus"), "0x02")

    def defined_nic(self, *args):
        from lxml import etree

        inst = stopped_instance()
        inst.change_network(*args)
        return etree.fromstring(inst.wvm.defineXML.call_args[0][0]).findall("devices/interface")[2]

    def test_no_source_keeps_the_one_the_nic_has(self):
        nic = self.defined_nic("52:54:00:00:00:04", "52:54:00:00:00:04", None, None, "e1000", "")
        self.assertEqual((nic.get("type"), nic.find("source").attrib), ("direct", {"dev": "eth0", "mode": "vepa"}))
        self.assertEqual(nic.find("model").get("type"), "e1000")

    def test_unknown_old_mac_changes_nothing(self):
        inst = stopped_instance()
        with self.assertRaises(libvirtError):
            inst.change_network("52:54:00:00:00:09", "52:54:00:00:00:03", "default", "net", "virtio", "")
        inst.wvm.defineXML.assert_not_called()


class TestAddNetworkXml(unittest.TestCase):
    def attached(self, **kwargs):
        from lxml import etree

        inst = stopped_instance()
        inst.add_network(**kwargs)
        return etree.fromstring(inst.instance.attachDeviceFlags.call_args[0][0])

    def test_posted_values_cannot_inject_elements(self):
        iface = self.attached(
            mac_address="52:54:00:00:00:05",
            source="default",
            model="virtio'/><filesystem type='mount'/><model type='x",
            nwfilter="f'/><evil/>",
        )
        self.assertEqual([el.tag for el in iface], ["mac", "source", "model", "filterref"])
        self.assertEqual(iface.find("model").get("type"), "virtio'/><filesystem type='mount'/><model type='x")

    def test_missing_mac_is_left_to_libvirt(self):
        iface = self.attached(mac_address="", source="default")
        self.assertIsNone(iface.find("mac"))


if __name__ == "__main__":
    unittest.main()
