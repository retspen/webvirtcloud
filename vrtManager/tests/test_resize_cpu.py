"""A CPU topology fixes a VM's maximum vCPUs: another maximum is refused
before anything changes."""

import unittest
from unittest.mock import MagicMock

from lxml import etree
from vrtManager import util
from vrtManager.instance import wvmInstance

DOMAIN_XML = """<domain><vcpu placement='static' current='2'>{count}</vcpu><cpu mode='host-model'>{topology}</cpu>
<vcpus><vcpu id='0' enabled='yes' hotpluggable='no' order='1'/><vcpu id='1' enabled='yes' hotpluggable='yes' order='2'/></vcpus>
</domain>"""


def shut_off_vm(xml):
    inst = wvmInstance.__new__(wvmInstance)
    inst.instance = MagicMock()
    inst.wvm = MagicMock()
    inst._XMLDesc = MagicMock(return_value=xml)
    inst.get_status = MagicMock(return_value=5)
    inst.get_cur_vcpu = MagicMock(return_value=2)
    return inst


class ResizeCpuTests(unittest.TestCase):
    def test_a_maximum_the_topology_does_not_make_is_refused(self):
        inst = shut_off_vm(DOMAIN_XML.format(count=2, topology="<topology sockets='1' dies='1' cores='2' threads='1'/>"))
        with self.assertRaises(util.OperationError) as raised:
            inst.resize_cpu("2", "4")
        self.assertEqual(raised.exception.values, {"count": 2})
        inst.wvm.defineXML.assert_not_called()  # hotplug is not switched off either

    def test_the_maximum_of_the_topology_or_no_topology_is_set(self):
        for topology, count in (("<topology sockets='2' cores='2' threads='1'/>", "4"), ("", "4")):
            with self.subTest(topology):
                inst = shut_off_vm(DOMAIN_XML.format(count=2, topology=topology))
                inst.resize_cpu("3", count)
                # one definition: libvirt refusing it leaves the hotplug settings as they were
                tree = etree.fromstring(inst.wvm.defineXML.call_args.args[0])
                self.assertEqual(inst.wvm.defineXML.call_count, 1)
                vcpu = tree.find("vcpu")
                self.assertEqual((vcpu.text, vcpu.get("current")), ("4", "3"))
                self.assertEqual(tree.xpath("vcpus/vcpu[@enabled='yes']/@id"), ["0", "1", "2"])
