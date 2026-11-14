"""An RBD disk reaches Ceph as its pool does: the pool's user, its secret by
uuid or by usage and its monitors go into the disk's source, as text."""

import unittest
from unittest.mock import MagicMock

from lxml import etree
from vrtManager.instance import wvmInstance
from vrtManager.storage import rbd_source_children

ODD = "a'b\"c<d>&e"


def pool(auth):
    rbd = MagicMock()
    rbd.XMLDesc.return_value = (
        f"<pool type='rbd'><name>ceph</name><source><name>rbd</name>"
        f"<host name='mon1.example.com' port='6789'/><host name='mon2.example.com'/>{auth}</source></pool>")
    return rbd


def source(children):
    return etree.fromstring(f"<source protocol='rbd' name='rbd/vm'>{children}</source>")


class RbdSourceTests(unittest.TestCase):
    def test_the_secret_by_uuid_or_usage_and_the_monitors(self):
        for secret, attrib in (("uuid='aaaaaaaa-0000-4000-8000-000000000001'", {"uuid": "aaaaaaaa-0000-4000-8000-000000000001"}),
                               ("usage='ceph-key'", {"usage": "ceph-key"})):
            with self.subTest(secret):
                rbd = pool(f"<auth type='ceph' username='libvirt'><secret {secret}/></auth>")
                disk_source = source(rbd_source_children(rbd))
                self.assertEqual(disk_source.find("auth").get("username"), "libvirt")
                self.assertEqual(disk_source.find("auth/secret").attrib, {"type": "ceph", **attrib})
                self.assertEqual([host.attrib for host in disk_source.findall("host")],
                                 [{"name": "mon1.example.com", "port": "6789"}, {"name": "mon2.example.com"}])

    def test_values_are_text_and_a_pool_without_auth_has_none(self):
        escaped = ODD.replace("&", "&amp;").replace("<", "&lt;").replace("'", "&apos;")
        disk_source = source(rbd_source_children(pool(f"<auth type='ceph' username='{escaped}'><secret usage='k'/></auth>")))
        self.assertEqual(disk_source.find("auth").get("username"), ODD)
        self.assertIsNone(source(rbd_source_children(pool(""))).find("auth"))

    def test_an_attached_disk_takes_them(self):
        inst = wvmInstance.__new__(wvmInstance)
        inst.instance = MagicMock()
        inst.instance.isActive.return_value = False
        inst.attach_disk("vdb", "rbd/vm", rbd_source_children(pool("<auth type='ceph' username='libvirt'><secret usage='k'/></auth>")),
                         pool_type="rbd", target_bus="virtio", disk_type="network")
        disk = etree.fromstring(inst.instance.attachDeviceFlags.call_args.args[0])
        self.assertEqual(disk.find("source").get("name"), "rbd/vm")
        self.assertEqual(disk.find("source/auth/secret").get("usage"), "k")
