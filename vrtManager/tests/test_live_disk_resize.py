"""Live checks that a disk grows while its VM runs or is paused.

QEMU holds a running domain's image, so the size goes through blockResize;
the guest and the volume must both see it, and the persistent definition
stays as it was. Runs only with TEST_LIBVIRT_HOST set (see vrtManager/tests/livetest.py).
"""

import os
import unittest

import libvirt
from django.test import SimpleTestCase
from vrtManager.connection import connection_manager
from vrtManager.instance import wvmInstance

from vrtManager.tests import livetest

P = livetest.PREFIX
PERSISTENT = libvirt.VIR_DOMAIN_XML_INACTIVE | libvirt.VIR_DOMAIN_XML_SECURE


class LiveDiskResizeTestCase(SimpleTestCase):
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
        livetest.ensure_pool(cls.conn)
        cls.inventory = livetest.inventory(cls.conn)
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
        livetest.cleanup(self.conn)

    def vm(self, name, fmt):
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        vol = pool.createXML(
            f"<volume><name>{P}{name}.{fmt}</name><capacity unit='MiB'>64</capacity>"
            f"<target><format type='{fmt}'/></target></volume>",
            0,
        )
        dom = self.conn.defineXML(
            f"<domain type='kvm'><name>{P}{name}</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>"
            "<os><type arch='x86_64' machine='q35'>hvm</type></os><features><acpi/></features><devices>"
            f"<disk type='file' device='disk'><driver name='qemu' type='{fmt}'/>"
            f"<source file='{vol.path()}'/><target dev='vda' bus='virtio'/></disk></devices></domain>"
        )
        return dom, vol, wvmInstance(*self.args, f"{P}{name}")

    def test_a_disk_grows_while_the_vm_runs_or_is_paused(self):
        new_size = 96 << 20
        for state in ("running", "paused"):
            for fmt in ("qcow2", "raw"):
                with self.subTest(state=state, fmt=fmt):
                    try:
                        dom, vol, vm = self.vm(f"resize-{state}-{fmt}", fmt)
                        dom.create()
                        if state == "paused":
                            dom.suspend()
                        before = dom.XMLDesc(PERSISTENT)

                        disk = vm.get_disk_devices()[0]
                        vm.resize_disk([{"path": disk["path"], "size_new": new_size}])

                        self.assertEqual(dom.blockInfo(disk["path"])[0], new_size, "the guest's disk")
                        self.assertEqual(vol.info()[1], new_size, "the volume")
                        self.assertEqual(dom.XMLDesc(PERSISTENT), before)
                        self.assertEqual(dom.state()[0], libvirt.VIR_DOMAIN_PAUSED if state == "paused" else libvirt.VIR_DOMAIN_RUNNING)
                    finally:
                        livetest.cleanup(self.conn)
