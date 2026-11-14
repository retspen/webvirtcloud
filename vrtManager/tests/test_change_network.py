import unittest
from unittest.mock import MagicMock

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
    # the host's networks and filters: a card naming another is refused
    inst.wvm = MagicMock(**{"listNetworks.return_value": ["default"], "listDefinedNetworks.return_value": ["lab"],
                            "listNWFilters.return_value": ["clean-traffic", "no-mac-spoofing", "f'/><evil/>"]})
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

    def test_the_same_filter_keeps_its_parameters(self):
        from lxml import etree

        inst = stopped_instance()
        filtered = DOMAIN_XML.replace("<model type='virtio'/></interface>",
                                      "<model type='virtio'/><filterref filter='clean-traffic'>"
                                      "<parameter name='IP' value='192.0.2.10'/></filterref></interface>", 1)
        inst._XMLDesc = MagicMock(return_value=filtered)
        inst.change_network("52:54:00:00:00:01", "52:54:00:00:00:01", None, None, "virtio", "clean-traffic")
        nic = etree.fromstring(inst.wvm.defineXML.call_args[0][0]).find("devices/interface")
        self.assertEqual([(f.get("filter"), f.find("parameter").get("value")) for f in nic.findall("filterref")],
                         [("clean-traffic", "192.0.2.10")])

        inst.change_network("52:54:00:00:00:01", "52:54:00:00:00:01", None, None, "virtio", "no-mac-spoofing")
        nic = etree.fromstring(inst.wvm.defineXML.call_args[0][0]).find("devices/interface")
        self.assertEqual([(f.get("filter"), len(f)) for f in nic.findall("filterref")], [("no-mac-spoofing", 0)])

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

    def test_a_network_or_filter_the_host_does_not_have_is_refused(self):
        # libvirt saves such a card: the VM would then not start
        inst = stopped_instance()
        for args, why in ((("missing", "net", "virtio", ""), "This host has no network missing"),
                          (("default", "net", "virtio", "gone"), "This host has no network filter gone")):
            with self.subTest(why), self.assertRaisesRegex(libvirtError, why):
                inst.change_network("52:54:00:00:00:01", "52:54:00:00:00:01", *args)
        inst.wvm.defineXML.assert_not_called()
        with self.assertRaisesRegex(libvirtError, "This host has no network missing"):
            inst.add_network("", "missing")
        inst.instance.attachDeviceFlags.assert_not_called()
        # a stopped network is the host's too
        inst.add_network("", "lab")
        inst.instance.attachDeviceFlags.assert_called_once()


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

    def test_a_nic_is_seen_as_its_definition_reads(self):
        # the fingerprint a form sends back: another change to the NIC gives another
        inst = stopped_instance()
        before = {nic["mac"]: nic["seen"] for nic in inst.get_net_devices(config=True)}
        inst._XMLDesc.return_value = DOMAIN_XML.replace("<model type='virtio'/>\n<bandwidth>",
                                                        "<model type='virtio'/><filterref filter='clean-traffic'/>\n<bandwidth>")
        after = {nic["mac"]: nic["seen"] for nic in inst.get_net_devices(config=True)}
        self.assertNotEqual(before["52:54:00:00:00:02"], after["52:54:00:00:00:02"])
        self.assertEqual(before["52:54:00:00:00:01"], after["52:54:00:00:00:01"])


if __name__ == "__main__":
    unittest.main()
