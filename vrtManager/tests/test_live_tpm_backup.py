"""Live check that a shut-off VM's TPM state is read through libvirt, and
that state written under another VM's UUID is the one that VM starts with:
libvirt makes it swtpm's and does not manufacture a new TPM over it.

Runs only with TEST_LIBVIRT_HOST set (see vrtManager/tests/livetest.py), on
a host with swtpm.
"""

import os
import unittest
import uuid

import libvirt
from django.test import SimpleTestCase
from lxml import etree

from vrtManager.backup import wvmBackup
from vrtManager.connection import connection_manager, wvmConnect
from vrtManager.tests import livetest

TPM = "<tpm model='tpm-crb'><backend type='emulator' version='2.0'/></tpm>"


class LiveTpmBackupTestCase(SimpleTestCase):
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
        if wvmConnect(*cls.args).get_tpm_model("x86_64", "q35") is None:
            raise unittest.SkipTest("The host has no swtpm")
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

    def tearDown(self):
        # the TPM state goes with the VM
        for dom in self.conn.listAllDomains():
            if dom.name().startswith(livetest.PREFIX + "tpm"):
                if dom.isActive():
                    dom.destroy()
                dom.undefineFlags(livetest.UNDEFINE_FLAGS | libvirt.VIR_DOMAIN_UNDEFINE_TPM)

    def run_once(self, name):
        dom = livetest.define_vm(self.conn, name, [], extra_devices=TPM)
        dom.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)
        dom.destroy()
        return dom

    def test_the_state_is_kept_by_the_vm_it_is_restored_to(self):
        source = self.run_once(livetest.PREFIX + "tpm-a")
        proxy = wvmBackup(*self.args, source.name(), uuid=source.UUIDString())
        self.assertTrue(proxy.backup_plan()["tpm"])
        state = proxy.read_tpm()
        self.assertIn("tpm2-00.permall", state)
        self.assertNotIn(".lock", state)

        restored = livetest.define_vm(self.conn, livetest.PREFIX + "tpm-b", [], extra_devices=TPM)
        host = wvmConnect(*self.args)
        with host._tpm_pool(restored.UUIDString(), build=True) as pool:
            for name, data in state.items():
                host.upload_volume(pool, name, data, owner=(0, 0), mode="0600")
        restored.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)
        restored.destroy()

        copy = wvmBackup(*self.args, restored.name(), uuid=restored.UUIDString())
        self.assertEqual(copy.read_tpm(), state)
        with host._tpm_pool(restored.UUIDString()) as pool:
            permissions = etree.fromstring(pool.storageVolLookupByName("tpm2-00.permall").XMLDesc(0))
        self.assertNotEqual(permissions.findtext("target/permissions/owner"), "0")  # swtpm's now

    def test_a_vm_that_never_started_has_no_state(self):
        dom = livetest.define_vm(self.conn, livetest.PREFIX + "tpm-c", [], extra_devices=TPM)
        self.assertEqual(wvmBackup(*self.args, dom.name(), uuid=dom.UUIDString()).read_tpm(), {})
        with wvmConnect(*self.args)._tpm_pool(str(uuid.uuid4())) as pool:
            self.assertIsNone(pool)
