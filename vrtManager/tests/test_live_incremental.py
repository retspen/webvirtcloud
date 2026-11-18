"""Live check of incremental backups: a full push backup with a checkpoint,
then backups of the changed blocks into volumes whose backing file is the
previous backup (by its name), copied flat by createXMLFrom equal to the
guest's disk; and the checkpoints pruned to the newest.

Runs only with TEST_LIBVIRT_HOST set (see vrtManager/tests/livetest.py).
"""

import json
import os
import time
import unittest

import libvirt
import libvirt_qemu
from django.test import SimpleTestCase
from lxml import etree

from vrtManager.backup import wvmBackup
from vrtManager.connection import connection_manager, wvmConnect
from vrtManager.tests import livetest

NAME = livetest.PREFIX + "incremental"
MIB = 1024 * 1024


class LiveIncrementalTestCase(SimpleTestCase):
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
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        livetest.cleanup(cls.conn)
        super().tearDownClass()
        if livetest.inventory(cls.conn) != cls.inventory:
            raise AssertionError("Live tests changed objects outside the test namespace")

    def tearDown(self):
        for dom in self.conn.listAllDomains():
            if dom.name() == NAME:
                if dom.isActive():
                    dom.destroy()
                dom.undefineFlags(livetest.UNDEFINE_FLAGS | libvirt.VIR_DOMAIN_UNDEFINE_CHECKPOINTS_METADATA)
        livetest.cleanup(self.conn)

    def write(self, dom, pattern, offset):
        """A guest write, through the disk device's own block backend."""
        libvirt_qemu.qemuMonitorCommand(
            dom, f'qemu-io -d /machine/peripheral/virtio-disk0/virtio-backend "write -P {pattern} {offset} 1M"',
            libvirt_qemu.VIR_DOMAIN_QEMU_MONITOR_COMMAND_HMP)

    def backup(self, proxy, name, incremental=None, checkpoint=None, backing=None):
        disks = [{"dev": "vda", "capacity": 64 * MIB, "format": "qcow2"}]
        targets = proxy.make_live_targets(disks, livetest.POOL, {"vda": name}, 0, 0,
                                          backing={"vda": backing} if backing else None)
        proxy.begin_clone_backup(targets, incremental=incremental, checkpoint=checkpoint)
        while proxy.backup_progress() is not None:
            time.sleep(0.2)
        self.assertEqual(proxy.backup_result()[0], True)

    def test_a_chain_copies_flat_to_the_guests_disk(self):
        pool = livetest.ensure_pool(self.conn)
        disk = livetest.create_volume(self.conn, NAME + ".qcow2")
        dom = livetest.define_vm(self.conn, NAME, [disk])
        dom.create()
        proxy = wvmBackup(*self.args, NAME, uuid=dom.UUIDString())

        self.write(dom, "0xaa", 0)
        for offset in range(8, 16):
            self.write(dom, "0xdd", offset * MIB)
        self.backup(proxy, NAME + "-full.qcow2", checkpoint="wvc-1")
        self.write(dom, "0xbb", 2 * MIB)
        self.assertGreaterEqual(proxy.checkpoint_sizes("wvc-1", ["vda"])["vda"], MIB)  # the block written since
        self.backup(proxy, NAME + "-inc1.qcow2", incremental="wvc-1", checkpoint="wvc-2", backing=NAME + "-full.qcow2")
        self.write(dom, "0xcc", 4 * MIB)
        self.backup(proxy, NAME + "-inc2.qcow2", incremental="wvc-2", checkpoint="wvc-3", backing=NAME + "-inc1.qcow2")

        pool.refresh(0)
        inc2 = pool.storageVolLookupByName(NAME + "-inc2.qcow2")
        self.assertEqual(etree.fromstring(inc2.XMLDesc(0)).findtext("backingStore/path").rsplit("/", 1)[-1],
                         NAME + "-inc1.qcow2")
        # only the changed blocks: the incremental file is far smaller than the full one
        self.assertLess(inc2.info()[2], pool.storageVolLookupByName(NAME + "-full.qcow2").info()[2])

        flat = pool.createXMLFrom(f"<volume><name>{NAME}-flat.raw</name><capacity>{64 * MIB}</capacity>"
                                  "<target><format type='raw'/></target></volume>", inc2, 0)
        data = wvmConnect(*self.args).download_volume(flat)
        self.assertEqual(data[:MIB], b"\xaa" * MIB)
        self.assertEqual(data[2 * MIB:3 * MIB], b"\xbb" * MIB)
        self.assertEqual(data[4 * MIB:5 * MIB], b"\xcc" * MIB)
        self.assertEqual(data[MIB:2 * MIB].count(0), MIB)
        self.assertEqual(data[8 * MIB:16 * MIB], b"\xdd" * 8 * MIB)

        proxy.prune_checkpoints(keep={"wvc-3"}, known={"wvc-1": 1, "wvc-2": 2, "wvc-3": 3}, devs=["vda"])
        self.assertEqual([c.getName() for c in dom.listAllCheckpoints(0)], ["wvc-3"])
        nodes = json.loads(libvirt_qemu.qemuMonitorCommand(
            dom, json.dumps({"execute": "query-named-block-nodes", "arguments": {"flat": True}}), 0))["return"]
        self.assertEqual(sorted({b["name"] for n in nodes for b in n.get("dirty-bitmaps", [])}), ["wvc-3"])

        # after a migration the checkpoint's record is gone, its bitmap is not: the pruning finds it
        dom.checkpointLookupByName("wvc-3").delete(libvirt.VIR_DOMAIN_CHECKPOINT_DELETE_METADATA_ONLY)
        self.assertIsNone(proxy.checkpoint_sizes("wvc-3", ["vda"]))
        proxy.prune_checkpoints(keep=set(), known={"wvc-3": 3}, devs=["vda"])
        nodes = json.loads(libvirt_qemu.qemuMonitorCommand(
            dom, json.dumps({"execute": "query-named-block-nodes", "arguments": {"flat": True}}), 0))["return"]
        self.assertEqual([b for n in nodes for b in n.get("dirty-bitmaps", [])], [])
