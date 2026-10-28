"""Values from requests do not change the XPath queries they are used in."""

import unittest
from unittest.mock import Mock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager.connection import wvmConnect
from vrtManager.network import wvmNetwork
from vrtManager.nwfilters import wvmNWFilter

CAPS = """<capabilities><guest><arch name='x86_64'><wordsize>64</wordsize><emulator>/usr/bin/qemu-x86</emulator>
<machine canonical='pc-q35'>q35</machine></arch>
<arch name='aarch64'><emulator>/usr/bin/qemu-arm</emulator><machine>virt</machine></arch></guest></capabilities>"""

FILTER = """<filter name='f'><rule action='drop' direction='in' priority='1'><tcp/></rule>
<rule action='drop' direction='in' priority='2'><udp/></rule></filter>"""


class FakeConn:
    def __init__(self):
        self.defined = None

    def networkDefineXML(self, xml):
        self.defined = xml


class XPathValueTests(unittest.TestCase):
    def setUp(self):
        self.conn = wvmConnect.__new__(wvmConnect)
        self.conn.get_cap_xml = lambda: CAPS

    def test_arch_lookups(self):
        self.assertEqual(self.conn.get_emulator("x86_64"), "/usr/bin/qemu-x86")
        self.assertEqual(self.conn.get_machine_types("aarch64"), ["virt"])
        injected = "nope' or '1'='1"
        self.assertIsNone(self.conn.get_emulator(injected))
        self.assertEqual(self.conn.get_machine_types(injected), [])
        self.assertEqual(self.conn.get_capabilities(injected), {})

    def test_nwfilter_rule_is_matched_by_its_attributes(self):
        nwf = wvmNWFilter.__new__(wvmNWFilter)
        nwf._XMLDesc = lambda flags: FILTER
        # values with quotes or brackets are compared, not parsed as XPath
        for action in ("drop'][@priority='2", "it's"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                nwf.delete_rule(0, action, "in", "1")
        kept = nwf.delete_rule(1, "drop", "in", "2")
        self.assertEqual(kept.count("<rule "), 1)
        self.assertIn("priority=\"1\"", kept)
        # add_rule adds a rule of its own
        added = nwf.add_rule("<rule action='drop' direction='in' priority='2'><icmp/></rule>")
        self.assertEqual(added.count("<rule "), 3)

    def test_qos_direction_must_be_known(self):
        net = wvmNetwork.__new__(wvmNetwork)
        net.wvm = FakeConn()
        net.net = Mock(**{"XMLDesc.return_value": "<network><bandwidth><inbound average='1'/><outbound average='2'/></bandwidth></network>"})
        with self.assertRaises(ValueError):
            net.unset_qos("*")
        net.unset_qos("inbound")
        self.assertNotIn("inbound", net.wvm.defined)
        self.assertIn("outbound", net.wvm.defined)
