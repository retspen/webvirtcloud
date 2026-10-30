"""External snapshots go through libvirt's snapshot API; WebVirtCloud only
checks preconditions and picks the flags. libvirt is mocked here; the live
cases are in instances/tests/test_live_snapshots.py."""

import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

import libvirt
from libvirt import libvirtError
from vrtManager import instance as instance_module
from vrtManager import util
from vrtManager.instance import PERSISTENT_XML, wvmInstance

INTERNAL = libvirt.VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL
EXTERNAL = libvirt.VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL

DOMAIN = """<domain>
  <devices>
    <disk type='file' device='disk'><source file='/pool/a.qcow2'/><target dev='vda' bus='virtio'/></disk>
    <disk type='file' device='disk'><source file='/pool/later.qcow2'/><target dev='vdb' bus='virtio'/></disk>
    <disk type='file' device='cdrom'><target dev='sda' bus='sata'/></disk>
  </devices>
</domain>"""


def snapshot_xml(name, memory=False, disks=("vda",)):
    devices = "".join(
        f"<disk type='file' device='disk'><source file='/pool/{d}.qcow2'/><target dev='{d}'/></disk>" for d in disks
    )
    mem = "<memory snapshot='external' file='/pool/x.mem'/>" if memory else "<memory snapshot='no'/>"
    return (
        f"<domainsnapshot><name>{name}</name><description>d &amp; e</description>"
        f"<creationTime>1700000000</creationTime>{mem}"
        f"<domain><devices>{devices}</devices></domain></domainsnapshot>"
    )


def fake_snap(name, memory=False, disks=("vda",), current=False, children=0):
    snap = MagicMock()
    snap.getName.return_value = name
    snap.getXMLDesc.return_value = snapshot_xml(name, memory, disks)
    snap.isCurrent.return_value = current
    snap.numChildren.return_value = children
    return snap


GiB = 1024**3


def pools(p, disks, free):
    """disks: path -> (pool name, virtual size); free: pool name -> free
    bytes. A path not in disks is in no pool."""
    by_name = {}
    for name, available in free.items():
        by_name[name] = MagicMock(**{"name.return_value": name, "info.return_value": [2, 0, 0, available]})

    def lookup(path):
        if path not in disks:
            error = libvirtError("no volume")
            error.err = (libvirt.VIR_ERR_NO_STORAGE_VOL,)
            raise error
        name, size = disks[path]
        return MagicMock(**{"info.return_value": [0, size, 0],
                            "storagePoolLookupByVolume.return_value": by_name[name]})

    p.get_volume_by_path = MagicMock(side_effect=lookup)
    return by_name


def proxy(status=1, internal=(), external=(), xml=DOMAIN, jobs=None, managed_save=False):
    """A wvmInstance without a connection. internal/external are fake snapshots."""
    p = wvmInstance.__new__(wvmInstance)
    p._read_cache = None
    p._XMLDesc = lambda flags: xml
    p.get_status = lambda: status
    p.get_uuid = lambda: "11111111-2222-3333-4444-555555555555"
    p.get_cur_memory = lambda: 1024
    p.refresh_instance_pools = MagicMock()
    p._snapshotCreateXML = MagicMock()
    p.wvm = MagicMock()
    dom = MagicMock()
    snaps = {s.getName(): s for s in (*internal, *external)}

    def list_names(flag):
        return [s.getName() for s in {INTERNAL: internal, EXTERNAL: external}.get(flag, (*internal, *external))]

    def list_all(flag):
        return list({INTERNAL: internal, EXTERNAL: external}[flag])

    dom.snapshotListNames.side_effect = list_names
    dom.listAllSnapshots.side_effect = list_all
    dom.snapshotLookupByName.side_effect = lambda name, flags: snaps[name]
    current = [s for s in snaps.values() if s.isCurrent()]
    dom.hasCurrentSnapshot.return_value = bool(current)
    dom.snapshotCurrent.return_value = current[0] if current else None
    dom.hasManagedSaveImage.return_value = managed_save
    dom.isActive.return_value = status in (1, 3)
    dom.blockJobInfo.side_effect = lambda dev, flags: (jobs or {}).get(dev, {})
    dom.XMLDesc.side_effect = lambda flags: xml
    p.instance = dom
    pools(p, {"/pool/a.qcow2": ("default", 20 * GiB), "/pool/later.qcow2": ("default", 20 * GiB)},
          {"default": 100 * GiB})
    return p


class SnapshotListTestCase(unittest.TestCase):
    def test_entries_carry_memory_current_and_description(self):
        p = proxy(external=[fake_snap("one", memory=True, current=True)])
        [entry] = p.get_snapshot(EXTERNAL)
        self.assertEqual(entry["name"], "one")
        self.assertEqual(entry["description"], "d & e")
        self.assertEqual(entry["date"], datetime.fromtimestamp(1700000000))
        self.assertTrue(entry["memory"])
        self.assertTrue(entry["current"])

    def test_detaches_lists_disks_missing_from_the_snapshot(self):
        p = proxy(external=[fake_snap("one", disks=("vda",))])
        [entry] = p.get_snapshot(EXTERNAL)
        self.assertEqual(entry["detaches"], [{"dev": "vdb", "path": "/pool/later.qcow2"}])

    def test_detaches_covers_the_persistent_and_the_live_definition(self):
        # vdc was hot-plugged into the running VM only; vdb waits for the next start
        live = DOMAIN.replace("/pool/later.qcow2", "/pool/live-only.qcow2").replace("dev='vdb'", "dev='vdc'")
        p = proxy(external=[fake_snap("one")])
        p._XMLDesc = lambda flags: DOMAIN if flags == PERSISTENT_XML else live
        [entry] = p.get_snapshot(EXTERNAL)
        self.assertEqual(
            entry["detaches"],
            [{"dev": "vdb", "path": "/pool/later.qcow2"}, {"dev": "vdc", "path": "/pool/live-only.qcow2"}],
        )

    def test_the_live_definition_is_compared_with_the_snapshots_live_one(self):
        # taken while vdc was hot-plugged: <domain> is what ran, <inactiveDomain> what was defined
        snap = fake_snap("one")
        snap.getXMLDesc.return_value = snapshot_xml("one", disks=("vda", "vdc")).replace(
            "</domainsnapshot>",
            "<inactiveDomain><devices><disk type='file' device='disk'><source file='/pool/vda.qcow2'/>"
            "<target dev='vda'/></disk></devices></inactiveDomain></domainsnapshot>",
        )
        persistent = DOMAIN.replace("<disk type='file' device='disk'><source file='/pool/later.qcow2'/><target dev='vdb' bus='virtio'/></disk>", "")
        live = DOMAIN.replace("/pool/later.qcow2", "/pool/live-only.qcow2").replace("dev='vdb'", "dev='vdc'")
        p = proxy(external=[snap])
        p._XMLDesc = lambda flags: persistent if flags == PERSISTENT_XML else live
        [entry] = p.get_snapshot(EXTERNAL)
        self.assertEqual(entry["detaches"], [])

    def test_a_shut_off_vm_is_compared_with_the_persistent_definition_only(self):
        p = proxy(status=5, external=[fake_snap("one", disks=("vda", "vdb"))])
        p._XMLDesc = MagicMock(return_value=DOMAIN)
        [entry] = p.get_snapshot(EXTERNAL)
        self.assertEqual(entry["detaches"], [])
        p._XMLDesc.assert_called_once_with(PERSISTENT_XML)

    def test_lists_are_by_kind(self):
        p = proxy(internal=[fake_snap("i")], external=[fake_snap("e")])
        self.assertEqual([s["name"] for s in p.get_snapshot(INTERNAL)], ["i"])
        self.assertEqual([s["name"] for s in p.get_snapshot(EXTERNAL)], ["e"])


class SnapshotJobsTestCase(unittest.TestCase):
    def test_running_jobs_are_reported_per_disk(self):
        p = proxy(jobs={"vda": {"cur": 5, "end": 10, "type": 3, "bandwidth": 0}})
        self.assertEqual(p.get_snapshot_jobs(), [{"dev": "vda", "cur": 5, "end": 10}])

    def test_a_stopped_vm_without_a_job_has_none(self):
        self.assertEqual(proxy(status=5).get_snapshot_jobs(), [])

    def test_an_offline_merge_of_a_stopped_vm_is_reported(self):
        # libvirt deletes an external snapshot of a shut-off VM as an offline block job
        p = proxy(status=5, jobs={"vdb": {"cur": 3, "end": 8, "type": 4, "bandwidth": 0}})
        p._XMLDesc = lambda flags: DOMAIN if flags == PERSISTENT_XML else "<domain><devices/></domain>"
        self.assertEqual(p.get_snapshot_jobs(), [{"dev": "vdb", "cur": 3, "end": 8}])

    def test_a_libvirt_without_offline_jobs_reports_none(self):
        err = libvirtError("domain is not running")
        err.err = (libvirt.VIR_ERR_OPERATION_INVALID,)
        p = proxy(status=5)
        p.instance.blockJobInfo.side_effect = err
        self.assertEqual(p.get_snapshot_jobs(), [])

    def test_another_error_of_a_stopped_vm_propagates(self):
        err = libvirtError("cannot reach the host")
        err.err = (libvirt.VIR_ERR_SYSTEM_ERROR,)
        p = proxy(status=5)
        p.instance.blockJobInfo.side_effect = err
        with self.assertRaises(libvirtError):
            p.get_snapshot_jobs()

    def test_a_running_vm_does_not_swallow_operation_invalid(self):
        err = libvirtError("operation invalid")
        err.err = (libvirt.VIR_ERR_OPERATION_INVALID,)
        p = proxy()
        p.instance.blockJobInfo.side_effect = err
        with self.assertRaises(libvirtError):
            p.get_snapshot_jobs()

    def test_a_running_vm_reads_the_live_disks(self):
        p = proxy(jobs={"vdb": {"cur": 1, "end": 2}})
        p._XMLDesc = lambda flags: DOMAIN if flags == 0 else "<domain><devices/></domain>"
        self.assertEqual(p.get_snapshot_jobs(), [{"dev": "vdb", "cur": 1, "end": 2}])


class SnapshotLookupTestCase(unittest.TestCase):
    def test_a_name_of_the_other_kind_is_refused(self):
        p = proxy(internal=[fake_snap("i")], external=[fake_snap("e")])
        with self.assertRaises(util.OperationError):
            p._snapshot("i", external=True)
        with self.assertRaises(util.OperationError):
            p._snapshot("e", external=False)
        self.assertEqual(p._snapshot("e", external=True).getName(), "e")


class SnapshotStateTestCase(unittest.TestCase):
    def test_managed_save_is_refused(self):
        with self.assertRaisesRegex(util.OperationError, "saved state"):
            proxy(managed_save=True)._check_snapshot_state()

    def test_running_job_is_refused(self):
        with self.assertRaisesRegex(util.OperationError, "still running"):
            proxy(jobs={"vda": {"cur": 1, "end": 2}})._check_snapshot_state()

    def test_an_offline_merge_of_a_stopped_vm_is_refused(self):
        with self.assertRaisesRegex(util.OperationError, "still running"):
            proxy(status=5, jobs={"vda": {"cur": 1, "end": 2}})._check_snapshot_state()

    def test_a_mixed_vm_passes_so_it_can_be_cleaned_up(self):
        proxy(internal=[fake_snap("i")], external=[fake_snap("e")])._check_snapshot_state()

    def test_a_clean_vm_passes(self):
        proxy()._check_snapshot_state()

    def test_internal_snapshots_are_refused_alike(self):
        # a saved state or a running job refuses internal create, revert and delete too
        for state in ({"managed_save": True}, {"jobs": {"vda": {"cur": 1, "end": 2}}}):
            for name, act in (("create", lambda p: p.create_snapshot("s")),
                              ("revert", lambda p: p.snapshot_revert("i")),
                              ("delete", lambda p: p.snapshot_delete("i"))):
                with self.subTest(name, **{key: True for key in state}):
                    p = proxy(status=5, internal=[fake_snap("i")], **state)
                    with self.assertRaises(util.OperationError):
                        act(p)
                    p.instance.revertToSnapshot.assert_not_called()
                    p._snapshotCreateXML.assert_not_called()

    def test_an_internal_snapshot_is_reverted_to_on_a_shut_off_vm(self):
        for status in (1, 3):
            with self.subTest(status=status), self.assertRaisesRegex(util.OperationError, "Shut the VM down"):
                proxy(status=status, internal=[fake_snap("i")]).snapshot_revert("i")
        p = proxy(status=5, internal=[fake_snap("i")])
        p.snapshot_revert("i")
        p.instance.revertToSnapshot.assert_called_once()


DISK_ONLY_ATOMIC = libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_ATOMIC


def created(p):
    xml, flags = p._snapshotCreateXML.call_args[0]
    return xml, flags


class CreateTestCase(unittest.TestCase):
    def test_disk_only_snapshot(self):
        p = proxy()
        p.create_external_snapshot("snap-1", "desc")
        xml, flags = created(p)
        self.assertEqual(flags, DISK_ONLY_ATOMIC)
        self.assertIn("<name>snap-1</name>", xml)
        self.assertNotIn("<memory", xml)
        # before, for the free space; after, for the new overlays
        self.assertEqual(p.refresh_instance_pools.call_count, 2)

    def test_description_is_escaped(self):
        p = proxy()
        p.create_external_snapshot("s", "<x> & 'y'")
        xml, _ = created(p)
        self.assertIn("&lt;x&gt; &amp;", xml)
        self.assertNotIn("<x>", xml)

    def test_memory_snapshot_goes_into_the_first_disks_pool(self):
        p = proxy()
        p.create_external_snapshot("m", memory=True)
        xml, flags = created(p)
        self.assertEqual(flags, libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_ATOMIC)
        self.assertIn(
            "<memory snapshot='external' file='/pool/11111111-2222-3333-4444-555555555555.m.mem'/>", xml
        )

    def test_a_quiesced_snapshot_freezes_the_guest_file_systems(self):
        p = proxy()
        p.is_agent_ready = lambda: True
        with patch.object(instance_module, "qemuAgentCommand", return_value='{"return": {}}') as agent:
            p.create_external_snapshot("q", quiesce=True)
        self.assertEqual(agent.call_args.args[1:], ('{"execute": "guest-ping"}', 10, 0))
        _, flags = created(p)
        self.assertEqual(flags, DISK_ONLY_ATOMIC | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE)

    def test_a_quiesced_snapshot_needs_an_agent_that_answers(self):
        # libvirt's quiesce asks the agent without a timeout: a hung agent is
        # found by a timed ping first
        p = proxy()
        p.is_agent_ready = lambda: True
        with patch.object(instance_module, "qemuAgentCommand",
                          side_effect=libvirtError("guest agent didn't respond to command within '10' seconds")):
            with self.assertRaises(libvirtError):
                p.create_external_snapshot("q", quiesce=True)
        p._snapshotCreateXML.assert_not_called()

    def test_quiesce_needs_a_running_vm_with_its_agent_and_no_memory(self):
        # libvirt accepts quiesce only for disk-only snapshots, through the agent
        for status, ready, memory, pattern in (
            (5, True, False, "running VM"), (3, True, False, "running VM"),
            (1, False, False, "guest agent is not connected"), (1, True, True, "memory"),
        ):
            with self.subTest(status=status, ready=ready, memory=memory):
                p = proxy(status=status)
                p.is_agent_ready = lambda ready=ready: ready
                self.refused(p, pattern, quiesce=True, memory=memory)

    def refused(self, p, pattern, **kwargs):
        with self.assertRaisesRegex(util.OperationError, pattern):
            p.create_external_snapshot(kwargs.pop("name", "s"), **kwargs)
        p._snapshotCreateXML.assert_not_called()

    def test_invalid_names_are_refused(self):
        for name in ("", ".hidden", "a/b", "a b", "x" * 65, "<x>"):
            with self.subTest(name=name):
                self.refused(proxy(), "Snapshot names", name=name)

    def test_names_are_checked_only_on_create(self):
        # snapshots made by the old code are named s1.<name> and stay usable
        p = proxy(external=[fake_snap("s1.old", current=True)])
        p.instance.revertToSnapshot = MagicMock()
        p.revert_external_snapshot("s1.old")
        p.instance.revertToSnapshot.assert_called_once()

    def test_a_taken_name_is_refused(self):
        self.refused(proxy(external=[fake_snap("s", current=True)]), "already exists")

    def test_shared_state_checks_apply(self):
        self.refused(proxy(managed_save=True), "saved state")

    def test_internal_snapshots_are_refused(self):
        self.refused(proxy(internal=[fake_snap("i")]), "internal snapshots")

    def test_newer_snapshots_after_a_revert_are_refused(self):
        self.refused(proxy(external=[fake_snap("old", current=True, children=1)]), "Newer snapshots")

    def test_snapshots_without_a_current_one_are_refused(self):
        # a create would start a second root
        self.refused(proxy(external=[fake_snap("old")]), "revert to a snapshot first")

    def test_a_disk_that_is_not_a_file_is_refused(self):
        xml = "<domain><devices><disk type='block' device='disk'><source dev='/dev/vg/x'/><target dev='vda'/></disk></devices></domain>"
        self.refused(proxy(xml=xml), "vda is not a file")

    def test_cdrom_with_media_is_refused(self):
        xml = DOMAIN.replace("<target dev='sda'", "<source file='/iso/x.iso'/><target dev='sda'")
        self.refused(proxy(xml=xml), "Eject")

    def test_memory_needs_a_running_vm(self):
        self.refused(proxy(status=3), "running VM", memory=True)
        self.refused(proxy(status=5), "running VM", memory=True)

    def test_memory_needs_a_pool(self):
        p = proxy()
        p.get_volume_by_path = MagicMock(side_effect=libvirtError("no volume"))
        self.refused(p, "not in a storage pool", memory=True)

    def space(self, disks, free, memory=False):
        """Creates a snapshot of a VM with these disks (path -> (pool, size)) and free space per pool."""
        xml = "<domain><devices>%s</devices></domain>" % "".join(
            f"<disk type='file' device='disk'><source file='{path}'/><target dev='vd{chr(97 + i)}'/></disk>"
            for i, path in enumerate(disks)
        )
        p = proxy(xml=xml)
        pools(p, {path: disk for path, disk in disks.items() if disk}, free)
        p.create_external_snapshot("s", memory=memory)
        return p

    def test_each_pool_keeps_a_tenth_of_its_disks_free(self):
        # a disk-only overlay grows as the guest writes, and a delete merges it down
        disks = {"/fast/a.qcow2": ("fast", 20 * GiB), "/slow/b.qcow2": ("slow", 50 * GiB)}
        self.space(disks, {"fast": 2 * GiB, "slow": 5 * GiB})
        with self.assertRaisesRegex(util.OperationError, r"Storage pool slow has 4\.9 GiB free; the snapshot needs 5\.0 GiB"):
            self.space(disks, {"fast": 2 * GiB, "slow": int(4.9 * GiB)})

    def test_at_least_one_gib_is_kept_free(self):
        self.space({"/pool/small.qcow2": ("default", 2 * GiB)}, {"default": GiB})
        with self.assertRaisesRegex(util.OperationError, "needs 1.0 GiB"):
            self.space({"/pool/small.qcow2": ("default", 2 * GiB)}, {"default": GiB - 1})

    def test_the_memory_pool_also_needs_room_for_the_memory(self):
        # get_cur_memory: 1024 MiB
        disks = {"/pool/a.qcow2": ("default", 20 * GiB)}
        self.space(disks, {"default": 3 * GiB}, memory=True)
        with self.assertRaisesRegex(util.OperationError, "needs 3.0 GiB"):
            self.space(disks, {"default": 3 * GiB - 1}, memory=True)

    def test_the_share_and_the_minimum_can_be_changed(self):
        disks = {"/pool/a.qcow2": ("default", 20 * GiB)}
        p = proxy()
        pools(p, disks, {"default": 4 * GiB - 1})
        with self.assertRaisesRegex(util.OperationError, r"needs 4\.0 GiB \(20% of the VM's disks in it, at least 2 GiB"):
            p.create_external_snapshot("s", free_percent=20, free_min_gib=2)
        p.create_external_snapshot("s", free_percent=0, free_min_gib=0)  # no check
        p._snapshotCreateXML.assert_called_once()

    def test_a_volume_that_cannot_be_read_is_refused_not_skipped(self):
        p = proxy()
        p.get_volume_by_path = MagicMock(side_effect=libvirtError("permission denied"))
        with self.assertRaises(libvirtError):
            p.create_external_snapshot("s")
        p._snapshotCreateXML.assert_not_called()

    def test_a_disk_in_no_pool_is_not_checked(self):
        p = self.space({"/pool/a.qcow2": ("default", 20 * GiB), "/elsewhere/b.qcow2": None}, {"default": 2 * GiB})
        p._snapshotCreateXML.assert_called_once()


REVERT_RUNNING = libvirt.VIR_DOMAIN_SNAPSHOT_REVERT_RUNNING
REVERT_PAUSED = libvirt.VIR_DOMAIN_SNAPSHOT_REVERT_PAUSED


class RevertTestCase(unittest.TestCase):
    def reverted_with(self, status, memory=False):
        snap = fake_snap("s", memory=memory, current=True)
        p = proxy(status=status, external=[snap])
        p.revert_external_snapshot("s")
        p.instance.revertToSnapshot.assert_called_once_with(snap, unittest.mock.ANY)
        p.refresh_instance_pools.assert_called_once()
        return p.instance.revertToSnapshot.call_args[0][1]

    def test_disk_only_flags_keep_the_vm_state(self):
        self.assertEqual(self.reverted_with(1), REVERT_RUNNING)
        self.assertEqual(self.reverted_with(3), REVERT_PAUSED)
        self.assertEqual(self.reverted_with(5), 0)

    def test_memory_snapshot_resumes_as_saved(self):
        self.assertEqual(self.reverted_with(1, memory=True), 0)
        self.assertEqual(self.reverted_with(5, memory=True), 0)

    def test_shared_state_checks_apply(self):
        p = proxy(external=[fake_snap("s")], managed_save=True)
        with self.assertRaisesRegex(util.OperationError, "saved state"):
            p.revert_external_snapshot("s")
        p.instance.revertToSnapshot.assert_not_called()

    def collision(self):
        err = libvirtError("external snapshot file for disk vda already exists and is not a block device")
        err.get_error_code = lambda: libvirt.VIR_ERR_CONFIG_UNSUPPORTED
        return err

    def test_same_second_revert_collision_is_retried_once(self):
        # libvirt has already stopped a running VM when the overlay names
        # collide; the retry a second later finishes the revert.
        snap = fake_snap("s")
        p = proxy(external=[snap])
        p.instance.revertToSnapshot.side_effect = [self.collision(), None]
        with unittest.mock.patch("vrtManager.instance.time.sleep") as sleep:
            p.revert_external_snapshot("s")
        sleep.assert_called_once_with(1)
        self.assertEqual(
            p.instance.revertToSnapshot.call_args_list,
            [unittest.mock.call(snap, REVERT_RUNNING)] * 2,
        )

    def test_a_second_collision_is_reported_with_the_vm_state(self):
        p = proxy(external=[fake_snap("s")])
        p.instance.revertToSnapshot.side_effect = [self.collision(), self.collision()]
        p.instance.isActive.return_value = False
        with unittest.mock.patch("vrtManager.instance.time.sleep"):
            with self.assertRaisesRegex(util.OperationError, "try again in a moment.*shut off"):
                p.revert_external_snapshot("s")

    def test_other_libvirt_errors_pass_through(self):
        p = proxy(external=[fake_snap("s")])
        p.instance.revertToSnapshot.side_effect = libvirtError("boom")
        with self.assertRaises(libvirtError) as ctx:
            p.revert_external_snapshot("s")
        self.assertNotIsInstance(ctx.exception, util.OperationError)


    def test_an_old_uefi_snapshot_saved_with_a_rom_loader_is_refused(self):
        # The old code switched pflash to rom while taking the snapshot, so
        # the saved definition has rom; reverting would leave the VM unbootable.
        uefi = DOMAIN.replace("<devices>", "<os><loader readonly='yes' type='pflash'>/ovmf/CODE.fd</loader></os><devices>")
        snap = fake_snap("s1.old", current=True)
        snap.getXMLDesc.return_value = snapshot_xml("s1.old").replace(
            "<domain>", "<domain><os><loader readonly='yes' type='rom'>/ovmf/CODE.fd</loader></os>"
        )
        p = proxy(external=[snap], xml=uefi)
        with self.assertRaisesRegex(util.OperationError, "older version"):
            p.revert_external_snapshot("s1.old")
        p.instance.revertToSnapshot.assert_not_called()


    def test_an_old_running_uefi_snapshot_is_judged_by_its_inactive_definition(self):
        # a running VM's snapshot keeps the live definition (pflash) and the
        # persistent one (rom); the revert restores the persistent one
        uefi = DOMAIN.replace("<devices>", "<os><loader readonly='yes' type='pflash'>/ovmf/CODE.fd</loader></os><devices>")
        snap = fake_snap("s1.old", current=True)
        snap.getXMLDesc.return_value = snapshot_xml("s1.old").replace(
            "<domain>", "<domain><os><loader readonly='yes' type='pflash'>/ovmf/CODE.fd</loader></os>"
        ).replace(
            "</domainsnapshot>",
            "<inactiveDomain><os><loader readonly='yes' type='rom'>/ovmf/CODE.fd</loader></os>"
            "<devices/></inactiveDomain></domainsnapshot>",
        )
        p = proxy(external=[snap], xml=uefi)
        with self.assertRaisesRegex(util.OperationError, "older version"):
            p.revert_external_snapshot("s1.old")
        p.instance.revertToSnapshot.assert_not_called()

    def test_a_failed_retry_still_reports_the_vm_state(self):
        # the collision already stopped the VM; another error on the retry
        # must not hide that
        p = proxy(external=[fake_snap("s")])
        p.instance.revertToSnapshot.side_effect = [self.collision(), libvirtError("disk busy")]
        p.instance.isActive.return_value = False
        with unittest.mock.patch("vrtManager.instance.time.sleep"):
            with self.assertRaisesRegex(util.OperationError, "disk busy.*The VM is shut off"):
                p.revert_external_snapshot("s")


class DeleteTestCase(unittest.TestCase):
    def test_delete_is_one_libvirt_call(self):
        snap = fake_snap("s", current=True)
        p = proxy(external=[snap])
        p.delete_external_snapshot("s")
        snap.delete.assert_called_once_with(0)
        p.refresh_instance_pools.assert_called_once()

    def test_running_job_is_refused(self):
        snap = fake_snap("s")
        p = proxy(external=[snap], jobs={"vda": {"cur": 1, "end": 2}})
        with self.assertRaisesRegex(util.OperationError, "still running"):
            p.delete_external_snapshot("s")
        snap.delete.assert_not_called()


CHAIN = """<domain><devices>
  <disk type='file' device='disk'><source file='/pool/a.two'/><target dev='vda'/>
    <backingStore type='file'><source file='/pool/a.one'/>
      <backingStore type='file'><source file='/pool/a.qcow2'/><backingStore/></backingStore>
    </backingStore>
  </disk>
</devices></domain>"""


def chain_snap(name, overlay, memory=None):
    snap = fake_snap(name)
    mem = f"<memory snapshot='external' file='{memory}'/>" if memory else "<memory snapshot='no'/>"
    snap.getXMLDesc.return_value = (
        f"<domainsnapshot><name>{name}</name><creationTime>1700000000</creationTime>{mem}"
        f"<disks><disk name='vda' snapshot='external'><source file='{overlay}'/></disk></disks>"
        "<domain><devices/></domain></domainsnapshot>"
    )
    return snap


class LeftBehindTestCase(unittest.TestCase):
    """libvirt only logs a warning when it cannot remove a merged or
    discarded file (on NFS it removes them as the qemu user), so the delete
    and revert report the files nothing uses any more that still exist."""

    def delete_fixture(self, still_there):
        one = chain_snap("one", "/pool/a.one", memory="/pool/vm.one.mem")
        two = chain_snap("two", "/pool/a.two")
        p = proxy(external=[one, two])
        after = CHAIN.replace("<source file='/pool/a.one'/>", "<source file='/pool/a.qcow2'/>").replace(
            "<backingStore type='file'><source file='/pool/a.qcow2'/><backingStore/></backingStore>", "<backingStore/>"
        )
        p.instance.XMLDesc.side_effect = [CHAIN, after]
        p.instance.listAllSnapshots.side_effect = [[one, two], [two]]

        def volume(path):
            if path not in still_there:
                raise libvirtError("no volume")
            return MagicMock()

        p.get_volume_by_path = volume
        return p

    def run_delete(self, still_there):
        return self.delete_fixture(still_there).delete_external_snapshot("one")

    def test_a_recorded_state_gives_the_same_files(self):
        # the delete job records the state before the merge and compares later
        still_there = {"/pool/a.one", "/pool/vm.one.mem", "/pool/a.two", "/pool/a.qcow2"}
        p = self.delete_fixture(still_there)
        direct = p._left_behind(p._snapshot_files())
        p = self.delete_fixture(still_there)
        state = json.loads(json.dumps(p.snapshot_files_state()))  # as stored in the job
        self.assertEqual(p.left_behind_since(state), direct)
        self.assertEqual(direct, ["/pool/a.one", "/pool/vm.one.mem"])

    def test_files_libvirt_could_not_remove_are_reported(self):
        self.assertEqual(
            self.run_delete({"/pool/a.one", "/pool/vm.one.mem", "/pool/a.two", "/pool/a.qcow2"}),
            ["/pool/a.one", "/pool/vm.one.mem"],
        )

    def test_a_file_another_vm_uses_is_not_reported(self):
        # on NFS libvirt could not remove it, but another VM uses it now
        with patch.object(wvmInstance, "paths_in_use", return_value={"/pool/a.one"}) as in_use, \
                patch.object(wvmInstance, "backing_path", return_value=None):
            left = self.run_delete({"/pool/a.one", "/pool/vm.one.mem", "/pool/a.two", "/pool/a.qcow2"})
        self.assertEqual(left, ["/pool/vm.one.mem"])
        # their own backing files do not keep each other
        in_use.assert_called_once_with(own=["/pool/a.one", "/pool/vm.one.mem"])

    def test_a_file_below_one_another_vm_uses_is_not_reported(self):
        # the other VM is shut off: its definition does not list the backing
        # file, and the in-use top's own backing reference does not count
        backing = {"/pool/a.one": "/pool/vm.one.mem"}
        with patch.object(wvmInstance, "paths_in_use", return_value={"/pool/a.one"}), \
                patch.object(wvmInstance, "backing_path", side_effect=backing.get):
            left = self.run_delete({"/pool/a.one", "/pool/vm.one.mem", "/pool/a.two", "/pool/a.qcow2"})
        self.assertEqual(left, [])

    def test_nothing_is_reported_when_libvirt_removed_them(self):
        # files still in use (base, the newer overlay) are never reported
        self.assertEqual(self.run_delete({"/pool/a.two", "/pool/a.qcow2"}), [])

    def revert(self, before, after, backing):
        """Revert to one; backing maps each file still on disk to its backing file."""
        one = chain_snap("one", "/pool/a.one")
        p = proxy(external=[one])
        p.instance.XMLDesc.side_effect = [before, after]
        p.instance.listAllSnapshots.side_effect = [[one], [one]]

        def volume(path):
            if path not in backing:
                raise libvirtError("no volume")
            if isinstance(backing[path], Exception):  # removed between the lookup and the read
                return MagicMock(**{"XMLDesc.side_effect": backing[path]})
            parent = f"<backingStore><path>{backing[path]}</path></backingStore>" if backing[path] else ""
            return MagicMock(**{"XMLDesc.return_value": f"<volume><target><path>{path}</path></target>{parent}</volume>"})

        p.get_volume_by_path = volume
        return p.revert_external_snapshot("one")

    def test_revert_reports_a_discarded_overlay_left_on_disk(self):
        before = CHAIN.replace("/pool/a.two", "/pool/a.after")
        after = CHAIN.replace("/pool/a.two", "/pool/a.1700000001")
        left = self.revert(before, after, {"/pool/a.after": "/pool/a.one", "/pool/a.1700000001": "/pool/a.one"})
        self.assertEqual(left, ["/pool/a.after"])

    def test_a_shut_off_vm_overlay_is_found_through_the_storage(self):
        # a shut-off VM's definition does not show the backing chain
        def plain(top):
            return f"<domain><devices><disk type='file' device='disk'><source file='{top}'/><target dev='vda'/></disk></devices></domain>"

        left = self.revert(plain("/pool/a.after"), plain("/pool/a.1700000001"), {"/pool/a.after": "/pool/a.one"})
        self.assertEqual(left, ["/pool/a.after"])

    def test_revert_never_reports_a_detached_disk(self):
        # vdb and vdc were added after the snapshot: the revert detaches them
        # and keeps their files on purpose, also when vdc is itself an overlay
        later = (
            "<disk type='file' device='disk'><source file='/pool/later.qcow2'/><target dev='vdb'/></disk>"
            "<disk type='file' device='disk'><source file='/pool/clone.qcow2'/><target dev='vdc'/>"
            "<backingStore type='file'><source file='/templates/base.qcow2'/><backingStore/></backingStore></disk>"
        )
        before = CHAIN.replace("</devices>", later + "</devices>")
        left = self.revert(before, CHAIN, {"/pool/later.qcow2": None, "/pool/clone.qcow2": "/templates/base.qcow2"})
        self.assertEqual(left, [])

    def test_revert_never_reports_a_detached_overlay_of_a_snapshot_file(self):
        linked = (
            "<disk type='file' device='disk'><source file='/pool/linked.qcow2'/><target dev='vdb'/>"
            "<backingStore type='file'><source file='/pool/a.one'/><backingStore/></backingStore></disk>"
        )
        before = CHAIN.replace("</devices>", linked + "</devices>")
        left = self.revert(before, CHAIN, {"/pool/linked.qcow2": "/pool/a.one"})
        self.assertEqual(left, [])

    def test_a_volume_gone_while_checking_is_not_reported(self):
        before = CHAIN.replace("/pool/a.two", "/pool/a.after")
        after = CHAIN.replace("/pool/a.two", "/pool/a.1700000001")
        left = self.revert(before, after, {"/pool/a.after": libvirtError("no volume")})
        self.assertEqual(left, [])


class PoolRefreshTestCase(unittest.TestCase):
    """The pools are refreshed after libvirt made, reverted or deleted the
    snapshot; a refresh error does not turn that into a failure. A create
    also refreshes them before, to read their free space."""

    def test_create_succeeds_when_the_refresh_after_it_fails(self):
        p = proxy()
        p.refresh_instance_pools.side_effect = [None, libvirtError("pool busy")]
        p.create_external_snapshot("one")
        p._snapshotCreateXML.assert_called_once()

    def test_create_is_refused_when_the_refresh_before_it_fails(self):
        # the free space is not known then
        p = proxy()
        p.refresh_instance_pools.side_effect = libvirtError("pool busy")
        with self.assertRaisesRegex(util.OperationError, "free space is unknown: pool busy"):
            p.create_external_snapshot("one")
        p._snapshotCreateXML.assert_not_called()

    def test_delete_and_revert_succeed_and_report_nothing_when_the_refresh_fails(self):
        for action in ("delete_external_snapshot", "revert_external_snapshot"):
            with self.subTest(action):
                snap = fake_snap("one", current=True)
                p = proxy(external=[snap])
                p.refresh_instance_pools.side_effect = libvirtError("pool busy")
                # a stale pool still lists every file
                p.get_volume_by_path = MagicMock()
                self.assertEqual(getattr(p, action)("one"), [])

class KindTestCase(unittest.TestCase):
    def test_internal_endpoints_refuse_external_names(self):
        snap = fake_snap("e")
        p = proxy(external=[snap])
        for call in (p.snapshot_revert, p.snapshot_delete):
            with self.subTest(call.__name__), self.assertRaises(util.OperationError):
                call("e")
        snap.delete.assert_not_called()
        p.instance.revertToSnapshot.assert_not_called()

    def test_external_endpoints_refuse_internal_names(self):
        snap = fake_snap("i")
        p = proxy(internal=[snap])
        for call in (p.revert_external_snapshot, p.delete_external_snapshot):
            with self.subTest(call.__name__), self.assertRaises(util.OperationError):
                call("i")
        snap.delete.assert_not_called()

    def test_internal_create_refuses_a_vm_with_external_snapshots(self):
        p = proxy(external=[fake_snap("e")])
        with self.assertRaisesRegex(util.OperationError, "external snapshots"):
            p.create_snapshot("i")
        p._snapshotCreateXML.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class DestroyFilesTestCase(unittest.TestCase):
    """Deleting a VM with its disks takes the files its external snapshots
    made or were taken on, not a template below them or a file another VM
    still grows from."""

    TOP = "<domain><devices><disk type='file' device='disk'><source file='/pool/a.two'/><target dev='vda'/></disk></devices></domain>"

    def split(self, other_overlay_on=None, top="/pool/a.two", extra=None):
        one = chain_snap("one", "/pool/a.one", memory="/pool/vm.one.mem")
        two = chain_snap("two", "/pool/a.two")
        snaps = [(one, "/pool/a.qcow2"), (two, "/pool/a.one")]  # each with the file it was taken on
        if extra:
            snaps.append((chain_snap("old", extra[0]), extra[1]))
        for snap, point in snaps:
            snap.getXMLDesc.return_value = snap.getXMLDesc.return_value.replace(
                "<devices/>", f"<devices><disk type='file' device='disk'><source file='{point}'/><target dev='vda'/></disk></devices>"
            )
        p = proxy(external=[snap for snap, _ in snaps], xml=self.TOP)
        p.get_disk_devices = lambda: [{"path": top}]
        backing = {
            "/pool/a.two": "/pool/a.one", "/pool/a.one": "/pool/a.qcow2", "/pool/a.qcow2": "/templates/base.qcow2",
        }
        if top == "/pool/a.reverted":
            backing[top] = "/pool/a.one"
        if extra:
            backing[extra[0]] = extra[1]
        # the template's own chain, longer than the VM's files
        template = ["/templates/base.qcow2"] + [f"/templates/base{n}.qcow2" for n in range(1, 10)]
        backing.update(zip(template, template[1:]))
        if other_overlay_on:
            backing["/pool/other.qcow2"] = other_overlay_on

        def volume(path):
            parent = f"<backingStore><path>{backing[path]}</path></backingStore>" if path in backing else ""
            vol = MagicMock(**{"XMLDesc.return_value": f"<volume>{parent}</volume>"})
            vol.path.return_value = path
            return vol

        p.get_volume_by_path = volume
        pool = MagicMock(**{"isActive.return_value": True})
        pool.listAllVolumes.return_value = [volume(path) for path in backing]
        no_seed = libvirtError("no volume")
        no_seed.err = (libvirt.VIR_ERR_NO_STORAGE_VOL,)
        pool.storageVolLookupByName.side_effect = no_seed  # the VM has no cloud-init seed
        p.wvm.listAllStoragePools.return_value = [pool]
        p.wvm.listAllDomains.return_value = []
        return p.split_disk_paths_by_use()

    def test_a_backing_file_that_cannot_be_read_is_an_error_not_the_chain_end(self):
        p = proxy()
        missing = libvirtError("no volume")
        missing.err = (libvirt.VIR_ERR_NO_STORAGE_VOL,)
        p.get_volume_by_path = MagicMock(side_effect=missing)
        self.assertIsNone(p.backing_path("/elsewhere/base.qcow2"))  # in no pool
        p.get_volume_by_path = MagicMock(side_effect=libvirtError("connection lost"))
        with self.assertRaises(libvirtError):
            p.backing_path("/pool/a.one")

    def test_the_snapshot_chain_and_memory_go_but_not_the_template(self):
        delete, keep = self.split()
        self.assertEqual(sorted(delete), ["/pool/a.one", "/pool/a.qcow2", "/pool/a.two", "/pool/vm.one.mem"])
        self.assertEqual(keep, [])

    def test_a_file_another_vm_grows_from_keeps_the_files_below_it(self):
        delete, keep = self.split(other_overlay_on="/pool/a.one")
        self.assertEqual(sorted(delete), ["/pool/a.two", "/pool/vm.one.mem"])
        self.assertEqual(sorted(keep), ["/pool/a.one", "/pool/a.qcow2"])

    def test_newer_snapshots_kept_after_a_revert_go_too(self):
        # reverted to one: the disk is a new overlay on a.one, and a.two of
        # snapshot two branches off it
        delete, keep = self.split(top="/pool/a.reverted")
        self.assertEqual(
            sorted(delete), ["/pool/a.one", "/pool/a.qcow2", "/pool/a.reverted", "/pool/a.two", "/pool/vm.one.mem"]
        )
        self.assertEqual(keep, [])

    def test_an_overlay_is_deleted_before_the_files_it_needs(self):
        # after a revert the branch a.two comes before a.one: if it cannot be deleted, a.one is still there
        delete, _ = self.split(top="/pool/a.reverted")
        for overlay, below in (("/pool/a.two", "/pool/a.one"), ("/pool/a.reverted", "/pool/a.one"),
                               ("/pool/a.one", "/pool/a.qcow2")):
            self.assertLess(delete.index(overlay), delete.index(below), (overlay, below))

    def test_a_snapshot_file_off_the_disks_chain_stays(self):
        # a disk detached since: its snapshot overlay grows from a file the
        # VM's disks do not
        delete, _ = self.split(extra=("/pool/gone.old", "/pool/gone.qcow2"))
        self.assertNotIn("/pool/gone.old", delete)
        self.assertNotIn("/pool/gone.qcow2", delete)
