"""Live checks for external snapshots on libvirt's own API. Runs only with
TEST_LIBVIRT_HOST set (see vrtManager/tests/livetest.py)."""

import os
import unittest

import libvirt
from django.test import SimpleTestCase
from lxml import etree
from vrtManager import util
from vrtManager.connection import connection_manager
from vrtManager.instance import wvmInstance

from vrtManager.tests import livetest

P = livetest.PREFIX


class LiveExternalSnapshotTestCase(SimpleTestCase):
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

    def vm(self, name, state="stopped", uefi=False, extra_devices=""):
        base = livetest.create_volume(self.conn, P + name)
        dom = livetest.define_vm(self.conn, P + name, [base], uefi=uefi, extra_devices=extra_devices)
        if state in ("running", "paused"):
            dom.create()
        if state == "paused":
            dom.suspend()
        return dom, wvmInstance(*self.args, None, uuid=dom.UUIDString())

    def pool_files(self, name):
        """The test pool's files whose names start with the VM's name."""
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        pool.refresh(0)
        return {vol for vol in pool.listVolumes() if vol.startswith(P + name + ".")}

    def top(self, dom):
        return etree.fromstring(dom.XMLDesc(0)).xpath("string(devices/disk[@device='disk']/source/@file)")

    def test_create_revert_delete_keep_the_state(self):
        for state, expected in (("stopped", libvirt.VIR_DOMAIN_SHUTOFF),
                                ("running", libvirt.VIR_DOMAIN_RUNNING),
                                ("paused", libvirt.VIR_DOMAIN_PAUSED)):
            with self.subTest(state):
                dom, vm = self.vm("snap-" + state, state)
                base = self.top(dom)
                vm.create_external_snapshot("one", "first")
                vm.create_external_snapshot("two")
                self.assertEqual(vm.revert_external_snapshot("one"), [], "files left behind")
                self.assertEqual(dom.state()[0], expected)
                self.assertEqual(vm.delete_external_snapshot("two"), [], "files left behind")
                self.assertEqual(vm.delete_external_snapshot("one"), [], "files left behind")
                self.assertEqual(self.pool_files("snap-" + state), {os.path.basename(base)}, "an overlay stayed on disk")
                self.assertEqual(dom.snapshotNum(0), 0)
                self.assertEqual(dom.state()[0], expected)
                self.assertTrue(livetest.volume_exists(self.conn, base))

    def test_memory_snapshot_resumes_and_its_file_goes_with_it(self):
        dom, vm = self.vm("snap-mem", "running")
        vm.create_external_snapshot("m", memory=True)
        mem = os.path.join(livetest.POOL_PATH, f"{dom.UUIDString()}.m.mem")
        self.assertTrue(livetest.volume_exists(self.conn, mem))
        dom.suspend()
        vm.revert_external_snapshot("m")
        self.assertEqual(dom.state()[0], libvirt.VIR_DOMAIN_RUNNING)
        self.assertEqual(vm.delete_external_snapshot("m"), [])
        self.assertFalse(livetest.volume_exists(self.conn, mem))

    def test_uefi_vm_keeps_its_loader(self):
        dom, vm = self.vm("snap-uefi", "running", uefi=True)
        os_before = etree.tostring(etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).find("os"))
        vm.create_external_snapshot("u")
        vm.revert_external_snapshot("u")
        vm.delete_external_snapshot("u")
        self.assertEqual(etree.tostring(etree.fromstring(dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE)).find("os")), os_before)
        self.assertEqual(dom.snapshotNum(0), 0)

    def test_a_shut_off_vm_without_a_merge_has_no_job(self):
        # libvirt reports a shut-off VM's merge as an offline block job; none runs here
        _, vm = self.vm("snap-nojob")
        self.assertEqual(vm.get_snapshot_jobs(), [])

    def test_back_to_back_reverts_keep_a_running_vm_running(self):
        # Without the retry, the second revert within one second stopped the VM.
        dom, vm = self.vm("snap-collide", "running")
        vm.create_external_snapshot("a")
        for _ in range(3):
            vm.revert_external_snapshot("a")
            vm.revert_external_snapshot("a")
            self.assertEqual(dom.state()[0], libvirt.VIR_DOMAIN_RUNNING)

    def test_a_disk_hot_plugged_live_only_is_named_and_detached_by_a_revert(self):
        dom, vm = self.vm("snap-hotplug", "running")
        vm.create_external_snapshot("a")
        extra = livetest.create_volume(self.conn, P + "snap-hotplug-extra")
        dom.attachDeviceFlags(
            f"<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='{extra}'/>"
            "<target dev='vdb' bus='virtio'/></disk>",
            libvirt.VIR_DOMAIN_AFFECT_LIVE,
        )
        [snap] = vm.get_snapshot(libvirt.VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL)
        self.assertEqual(snap["detaches"], [{"dev": "vdb", "path": extra}])
        self.assertEqual(vm.revert_external_snapshot("a"), [], "the detached disk is not a leftover")
        self.assertNotIn("vdb", etree.fromstring(dom.XMLDesc(0)).xpath("devices/disk/target/@dev"))
        self.assertEqual(dom.state()[0], libvirt.VIR_DOMAIN_RUNNING)
        self.assertTrue(livetest.volume_exists(self.conn, extra))
        vm.delete_external_snapshot("a")

    def test_a_mixed_vm_can_be_cleaned_up(self):
        dom, vm = self.vm("snap-mixed-clean")
        dom.snapshotCreateXML("<domainsnapshot><name>i</name></domainsnapshot>", 0)
        dom.snapshotCreateXML(
            "<domainsnapshot><name>e</name></domainsnapshot>", libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
        )
        # libvirt refuses an external snapshot whose parent is internal, so the
        # internal one goes first
        vm.snapshot_delete("i")
        vm.delete_external_snapshot("e")
        self.assertEqual(dom.snapshotNum(0), 0)

    def test_chain_stays_linear(self):
        dom, vm = self.vm("snap-linear")
        vm.create_external_snapshot("a")
        vm.create_external_snapshot("b")
        vm.revert_external_snapshot("a")
        with self.assertRaisesRegex(util.OperationError, "Newer snapshots"):
            vm.create_external_snapshot("c")
        vm.delete_external_snapshot("b")
        vm.create_external_snapshot("c")

    def test_refusals(self):
        iso = livetest.create_volume(self.conn, P + "snap-media")
        cdrom = (f"<disk type='file' device='cdrom'><driver name='qemu' type='qcow2'/><source file='{iso}'/>"
                 "<target dev='sda' bus='sata'/><readonly/></disk>")
        _, vm = self.vm("snap-cdrom", extra_devices=cdrom)
        with self.assertRaisesRegex(util.OperationError, "Eject"):
            vm.create_external_snapshot("x")

        dom, vm = self.vm("snap-saved", "running")
        dom.managedSave(0)
        with self.assertRaisesRegex(util.OperationError, "saved state"):
            vm.create_external_snapshot("x")

        dom, vm = self.vm("snap-mixed")
        dom.snapshotCreateXML("<domainsnapshot><name>i</name></domainsnapshot>", 0)
        with self.assertRaisesRegex(util.OperationError, "internal snapshots"):
            vm.create_external_snapshot("x")

    def test_quiesce_without_a_connected_agent_is_refused(self):
        # no guest OS runs an agent here: the channel exists but is not connected
        channel = "<channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>"
        for name, extra in (("snap-noagent", ""), ("snap-agentchan", channel)):
            with self.subTest(name):
                dom, vm = self.vm(name, "running", extra_devices=extra)
                with self.assertRaisesRegex(util.OperationError, "guest agent is not connected"):
                    vm.create_external_snapshot("q", quiesce=True)
                self.assertEqual(dom.snapshotNum(0), 0)

    def test_a_pool_without_room_for_the_overlays_is_refused(self):
        # a sparse disk ten times the pool: a tenth of it is more than the pool has free
        pool = self.conn.storagePoolLookupByName(livetest.POOL)
        big = livetest.create_volume(self.conn, P + "snap-big", size_mib=pool.info()[1] * 10 // 1024**2)
        dom = livetest.define_vm(self.conn, P + "snap-big", [big])
        vm = wvmInstance(*self.args, None, uuid=dom.UUIDString())
        with self.assertRaisesRegex(util.OperationError, f"Storage pool {livetest.POOL} has .* GiB free; the snapshot needs"):
            vm.create_external_snapshot("x")
        self.assertEqual(dom.snapshotNum(0), 0)
        vm.create_external_snapshot("x", free_percent=0, free_min_gib=0)
        vm.delete_external_snapshot("x")
