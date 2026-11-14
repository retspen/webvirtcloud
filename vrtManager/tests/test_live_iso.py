"""Live checks for ISO mount/unmount. Runs only with TEST_LIBVIRT_HOST set."""

import os
import unittest

import libvirt
from django.test import SimpleTestCase
from lxml import etree
from vrtManager.connection import connection_manager
from vrtManager.instance import wvmInstance

from vrtManager.tests import livetest

P = livetest.PREFIX
CDROMS = (
    "<disk type='file' device='cdrom'><driver name='qemu' type='raw'/><target dev='sda' bus='sata'/><readonly/></disk>"
    "<disk type='file' device='cdrom'><driver name='qemu' type='raw'/><target dev='sdb' bus='sata'/><readonly/></disk>"
    "<graphics type='vnc' autoport='yes' passwd='keep1234'/>"
)
PERSISTENT = libvirt.VIR_DOMAIN_XML_INACTIVE | libvirt.VIR_DOMAIN_XML_SECURE


class LiveIsoTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        if not livetest.enabled():
            raise unittest.SkipTest("Set TEST_LIBVIRT_HOST to run the live libvirt tests")
        cls.args = (
            os.environ["TEST_LIBVIRT_HOST"],
            os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            int(os.environ.get("TEST_LIBVIRT_TYPE", 4)),
        )
        cls.conn = connection_manager.get_connection(*cls.args)
        livetest.cleanup(cls.conn)
        pool = livetest.ensure_pool(cls.conn)
        cls.inventory = livetest.inventory(cls.conn)
        cls.iso = pool.createXML(
            f"<volume><name>{P}media.iso</name><capacity unit='MiB'>1</capacity><target><format type='raw'/></target></volume>", 0
        ).path()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            livetest.remove_pool(cls.conn)
        finally:
            super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")

    def tearDown(self):
        for dom in self.conn.listAllDomains():
            if dom.name().startswith(P):
                if dom.isActive():
                    dom.destroy()
                dom.undefineFlags(livetest.UNDEFINE_FLAGS)

    def vm(self, state):
        dom = livetest.define_vm(self.conn, P + "iso-" + state, [], extra_devices=CDROMS)
        if state in ("running", "paused"):
            dom.create()
        if state == "paused":
            dom.suspend()
        return dom, wvmInstance(*self.args, None, uuid=dom.UUIDString())

    def media(self, dom, flags):
        tree = etree.fromstring(dom.XMLDesc(flags))
        return {d.find("target").get("dev"): d.xpath("string(source/@file)") for d in tree.xpath("devices/disk[@device='cdrom']")}

    def test_mount_and_unmount_in_every_state(self):
        for state in ("stopped", "running", "paused"):
            with self.subTest(state):
                dom, vm = self.vm(state)
                try:
                    vm.mount_iso("sdb", os.path.basename(self.iso))
                    views = [PERSISTENT] + ([0] if dom.isActive() else [])
                    for flags in views:
                        self.assertEqual(self.media(dom, flags), {"sda": "", "sdb": self.iso}, f"flags={flags}")
                    self.assertIn("keep1234", dom.XMLDesc(PERSISTENT))

                    vm.umount_iso("sdb", self.iso)
                    for flags in views:
                        self.assertEqual(self.media(dom, flags), {"sda": "", "sdb": ""}, f"flags={flags}")
                    self.assertIn("keep1234", dom.XMLDesc(PERSISTENT))
                finally:
                    self.tearDown()

    def test_unknown_iso_or_device_changes_nothing(self):
        dom, vm = self.vm("running")
        before = (dom.XMLDesc(0), dom.XMLDesc(PERSISTENT))
        for dev, image in (("sdb", "no-such.iso"), ("sdz", os.path.basename(self.iso))):
            with self.subTest(dev=dev, image=image):
                with self.assertRaises(libvirt.libvirtError):
                    vm.mount_iso(dev, image)
                self.assertEqual((dom.XMLDesc(0), dom.XMLDesc(PERSISTENT)), before)
