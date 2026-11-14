"""A clone of a UEFI VM gets its own copy of the VM's NVRAM, with the
original's format, owner and mode, wherever the definition names the file."""

import contextlib
import unittest
from unittest.mock import MagicMock

from lxml import etree

from vrtManager import util
from vrtManager.instance import wvmInstance

ORIGINAL = """<volume><name>vm_VARS.qcow2</name><key>k</key><capacity>540672</capacity>
<target><path>/var/lib/libvirt/qemu/nvram/vm_VARS.qcow2</path><format type='qcow2'/>
<permissions><mode>0600</mode><owner>107</owner><group>107</group></permissions></target></volume>"""


def domain(nvram):
    return f"""<domain><name>vm</name><uuid>u</uuid><os><type>hvm</type>
<loader readonly='yes' type='pflash'>/usr/share/edk2/ovmf/OVMF_CODE.fd</loader>{nvram}</os><devices/></domain>"""


def proxy(nvram):
    p = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    p.get_status = lambda: 5
    p.get_instances = lambda: []
    p._XMLDesc = lambda flags: domain(nvram)
    p._defineXML = MagicMock()
    p.pool = MagicMock()
    p.pool.storageVolLookupByName.return_value.XMLDesc.return_value = ORIGINAL
    p.pool.createXMLFrom.return_value.path.return_value = "/var/lib/libvirt/qemu/nvram/copy_VARS.qcow2"
    p._nvram_pool = lambda: contextlib.nullcontext(p.pool)
    return p


class CloneNvramTestCase(unittest.TestCase):
    def test_the_copy_keeps_the_format_owner_and_mode(self):
        p = proxy("<nvram format='qcow2'>/var/lib/libvirt/qemu/nvram/vm_VARS.qcow2</nvram>")
        p.clone_instance({"name": "copy"}, "abababab-0000-1111-2222-333333333333")
        xml, original, _ = p.pool.createXMLFrom.call_args.args
        volume = etree.fromstring(xml)
        self.assertEqual(volume.findtext("name"), "copy_VARS.qcow2")
        self.assertEqual(volume.find("target/format").get("type"), "qcow2")
        self.assertEqual(volume.findtext("target/permissions/owner"), "107")
        self.assertIsNone(volume.find("target/path"))
        self.assertIs(original, p.pool.storageVolLookupByName.return_value)
        (defined,), _ = p._defineXML.call_args
        self.assertEqual(etree.fromstring(defined).findtext("os/nvram"), "/var/lib/libvirt/qemu/nvram/copy_VARS.qcow2")

    def test_an_nvram_source_element_points_at_the_copy(self):
        p = proxy("<nvram type='file'>\n  <source file='/var/lib/libvirt/qemu/nvram/vm_VARS.qcow2'/>\n</nvram>")
        p.clone_instance({"name": "copy"}, "abababab-0000-1111-2222-333333333333")
        p.pool.storageVolLookupByName.assert_called_once_with("vm_VARS.qcow2")
        (defined,), _ = p._defineXML.call_args
        self.assertEqual(
            etree.fromstring(defined).find("os/nvram/source").get("file"), "/var/lib/libvirt/qemu/nvram/copy_VARS.qcow2"
        )

    def test_an_nvram_that_is_not_a_file_is_refused_before_any_copy(self):
        p = proxy("<nvram type='network'><source protocol='iscsi' name='x'/></nvram>")
        with self.assertRaises(util.OperationError):
            p.clone_instance({"name": "copy"}, "abababab-0000-1111-2222-333333333333")
        p.pool.createXMLFrom.assert_not_called()
