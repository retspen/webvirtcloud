"""The host, pool, user and format values of a new Ceph or NFS pool go into
its XML as text, whatever characters they hold; a new pool that does not
start is not left defined."""

from unittest.mock import patch

from django.test import SimpleTestCase
from libvirt import libvirtError
from lxml import etree
from vrtManager.storage import wvmStorages

ODD = "a'b\"c<d>&e"


class PoolXmlTests(SimpleTestCase):
    def defined_xml(self, create, *args):
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            getattr(wvmStorages("host", "login", "pw", 1), create)(*args)
        return etree.fromstring(get.return_value.storagePoolDefineXML.call_args.args[0])

    def test_ceph_values_are_text(self):
        pool = self.defined_xml("create_storage_ceph", "rbd", "pool1", ODD + "pool", ODD + "host", ODD + "user", ODD + "secret")
        self.assertEqual(pool.findtext("source/name"), ODD + "pool")
        self.assertEqual(pool.find("source/host").get("name"), ODD + "host")
        self.assertEqual(pool.find("source/auth").get("username"), ODD + "user")
        self.assertEqual(pool.find("source/auth/secret").get("uuid"), ODD + "secret")

    def test_nfs_values_are_text(self):
        pool = self.defined_xml("create_storage_netfs", "netfs", "pool1", ODD + "host", "/srv/nfs", ODD + "fmt", "/mnt/pool1")
        self.assertEqual(pool.find("source/host").get("name"), ODD + "host")
        self.assertEqual(pool.find("source/format").get("type"), ODD + "fmt")
        self.assertEqual(pool.find("source/dir").get("path"), "/srv/nfs")

    def test_a_pool_that_does_not_start_is_undefined(self):
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            pool = get.return_value.storagePoolDefineXML.return_value
            pool.create.side_effect = libvirtError("mount failed")
            with self.assertRaises(libvirtError):
                wvmStorages("host", "login", "pw", 1).create_storage_netfs(
                    "netfs", "pool1", "nfs.example.com", "/srv/nfs", "auto", "/mnt/pool1")
        pool.undefine.assert_called_once_with()
        pool.setAutostart.assert_not_called()
