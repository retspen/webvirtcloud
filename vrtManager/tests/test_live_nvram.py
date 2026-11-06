"""Live check that the NVRAM file a migrated VM leaves behind is removed,
and kept when the destination sees the same directory.

Runs only with TEST_LIBVIRT_HOST set (see vrtManager/tests/livetest.py). The
deletion needs a second host: TEST_LIBVIRT_SSH_HOST (and _LOGIN).
"""

import os
import unittest

import libvirt
from django.test import SimpleTestCase
from lxml import etree

from vrtManager.tests import livetest
from vrtManager.connection import CONN_SSH, NVRAM_DIR, connection_manager, wvmConnect

NAME = livetest.PREFIX + "nvram"
PATH = f"{NVRAM_DIR}/{NAME}_VARS.fd"


class LiveRemoveNvramTestCase(SimpleTestCase):
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
        cls.inventory = livetest.inventory(cls.conn)
        cls.pools = {p.name() for p in cls.conn.listAllStoragePools()}
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        livetest.cleanup(cls.conn)
        super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")
        if {p.name() for p in cls.conn.listAllStoragePools()} != cls.pools:
            raise AssertionError("A storage pool was left behind")

    def leave_nvram(self):
        """What a migration with VIR_MIGRATE_UNDEFINE_SOURCE leaves: the file
        without a domain."""
        dom = self.conn.defineXML(
            f"<domain type='kvm'><name>{NAME}</name><memory unit='MiB'>128</memory><vcpu>1</vcpu>"
            "<os firmware='efi'><type arch='x86_64' machine='q35'>hvm</type></os>"
            "<features><acpi/></features><devices/></domain>"
        )
        dom.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)  # creates the file
        self.assertEqual(etree.fromstring(dom.XMLDesc(0)).findtext("os/nvram"), PATH)
        dom.destroy()
        dom.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)

    def tearDown(self):
        livetest.cleanup(self.conn)
        host = wvmConnect(*self.args)
        with host._nvram_pool() as pool:
            vol = host._find_volume(pool, os.path.basename(PATH))
            if vol is not None:
                vol.delete(0)

    def exists(self):
        host = wvmConnect(*self.args)
        with host._nvram_pool() as pool:
            return host._find_volume(pool, os.path.basename(PATH)) is not None

    def test_a_directory_both_connections_see_is_kept(self):
        self.leave_nvram()
        self.assertFalse(wvmConnect(*self.args).remove_nvram(PATH, wvmConnect(*self.args)))
        self.assertTrue(self.exists())

    def test_the_file_is_deleted_when_the_destination_is_another_host(self):
        other_host = os.environ.get("TEST_LIBVIRT_SSH_HOST")
        if not other_host or other_host == self.args[0]:
            self.skipTest("Set TEST_LIBVIRT_SSH_HOST to a second host")
        other = wvmConnect(other_host, os.environ.get("TEST_LIBVIRT_SSH_LOGIN", "root"), "", CONN_SSH)
        other_pools = {p.name() for p in other.wvm.listAllStoragePools()}
        self.leave_nvram()
        self.assertTrue(wvmConnect(*self.args).remove_nvram(PATH, other))
        self.assertFalse(self.exists())
        self.assertEqual({p.name() for p in other.wvm.listAllStoragePools()}, other_pools)
