"""A new volume: a pool of files (dir, fs, netfs) keeps the asked format,
the others make it raw; only qcow2 takes qcow2's options."""

from unittest.mock import patch

from django.test import SimpleTestCase
from lxml import etree
from vrtManager.create import wvmCreate


class NewVolumeTests(SimpleTestCase):
    def created(self, pool_type, fmt, metadata=True):
        """The volume XML and flags a new VM disk of format fmt gets in a pool of pool_type."""
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            pool = get.return_value.storagePoolLookupByName.return_value
            pool.XMLDesc.return_value = f"<pool type='{pool_type}'/>"
            wvmCreate("host", "login", "pw", 1).create_volume("pool1", "vm", 1, fmt, metadata)
        xml, flags = pool.createXML.call_args.args
        return etree.fromstring(xml), flags

    def test_a_file_pool_keeps_the_format(self):
        for pool_type in ("dir", "fs", "netfs"):
            with self.subTest(pool_type):
                volume, flags = self.created(pool_type, "qcow2")
                self.assertEqual((volume.findtext("name"), volume.find("target/format").get("type")), ("vm.qcow2", "qcow2"))
                self.assertEqual((volume.findtext("allocation"), flags), ("0", True))
                self.assertIsNotNone(volume.find("target/features/lazy_refcounts"))

    def test_other_pools_make_a_whole_raw_volume(self):
        for pool_type in ("logical", "rbd", "disk"):
            with self.subTest(pool_type):
                volume, flags = self.created(pool_type, "qcow2")
                self.assertEqual((volume.findtext("name"), volume.find("target/format").get("type")), ("vm", "raw"))
                self.assertEqual((volume.findtext("allocation"), flags), (str(1 << 30), False))
                self.assertIsNone(volume.find("target/compat"))

    def test_only_qcow2_takes_its_options(self):
        volume, _flags = self.created("dir", "qcow")
        self.assertEqual(volume.findtext("name"), "vm.qcow")
        self.assertIsNone(volume.find("target/compat"))
        self.assertIsNone(volume.find("target/features"))


class TemplateCopyTests(SimpleTestCase):
    def copied(self, pool_type, fmt):
        """The XML and flags of the copy of a template of format fmt into a pool of pool_type."""
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            template = get.return_value.storageVolLookupByPath.return_value
            template.XMLDesc.return_value = f"<volume><target><format type='{fmt}'/></target></volume>"
            pool = get.return_value.storagePoolLookupByName.return_value
            pool.XMLDesc.return_value = f"<pool type='{pool_type}'/>"
            wvmCreate("host", "login", "pw", 1).clone_from_template("vm", "/t/base", "pool1", True)
        xml, _template, flags = pool.createXMLFrom.call_args.args
        return etree.fromstring(xml), flags

    def test_a_file_pool_takes_a_file_copy(self):
        for pool_type in ("dir", "fs", "netfs"):
            with self.subTest(pool_type):
                volume, flags = self.copied(pool_type, "qcow2")
                self.assertEqual((volume.findtext("name"), flags), ("vm.img", True))
                self.assertIsNotNone(volume.find("target/features/lazy_refcounts"))

    def test_only_a_qcow2_copy_takes_its_options(self):
        for fmt in ("raw", "qcow"):
            with self.subTest(fmt):
                volume, _flags = self.copied("dir", fmt)
                self.assertEqual(volume.find("target/format").get("type"), fmt)
                self.assertIsNone(volume.find("target/compat"))
                self.assertIsNone(volume.find("target/features"))
