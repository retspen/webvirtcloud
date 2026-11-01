"""Migration with disks copied into pools of the destination: libvirt copies
the disks a pool is chosen for (NON_SHARED_DISK, only those targets), the
definitions name the new paths; every other file disk must be on storage
both hosts share. A shut-off VM is started paused for the copy and shut off
on the destination. Disks that cannot be copied are refused before anything
changes; the copies of a failed migration are removed again. A shut-off VM
with TPM state migrates paused too, copies or not: a live migration carries
that state, a file of the source host."""

import unittest
from unittest import mock

import libvirt
from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager import util
from vrtManager.connection import wvmConnect
from vrtManager.instance import wvmInstances

IMAGES = "/var/lib/libvirt/images"
FAST = "/srv/fast"


def error(code, message="error"):
    err = libvirt.libvirtError(message)
    err.err = (code, 0, message, 2, None, None, None, 0, 0)
    return err


def disk(path, target="vda", device="disk", fmt="qcow2", extra=""):
    return (f"<disk type='file' device='{device}'><driver name='qemu' type='{fmt}'/>"
            f"<source file='{path}'/><target dev='{target}'/>{extra}</disk>")


def domain(*disks):
    return f"<domain><devices>{''.join(disks)}</devices></domain>"


class Pool:
    def __init__(self, name, path, files=(), kind="dir"):
        self._name, self.path, self.kind = name, path, kind
        self.files = set(files)
        self.deleted = []

    def name(self):
        return self._name

    def XMLDesc(self, flags=0):
        return f"<pool type='{self.kind}'><name>{self._name}</name><target><path>{self.path}</path></target></pool>"

    def refresh(self, flags=0):
        pass

    def storageVolLookupByName(self, name):
        if name not in self.files:
            raise error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        volume = mock.Mock()
        volume.delete.side_effect = lambda flags: self.deleted.append(name)
        return volume


class Source:
    """The source host's wvmInstance: a VM in state with the given running
    (and next-start) definitions; its volumes have capacity and a backing
    file; pools: the directories it has as pools."""

    def __init__(self, state, xml, inactive=None, capacity=1 << 30, backing=None, pools=(IMAGES,)):
        self.state = state
        self.instance = mock.Mock()
        self.instance.XMLDesc.side_effect = lambda flags: inactive if inactive and flags & 2 else xml
        self.instance.snapshotNum.return_value = 0
        self.instance.hasManagedSaveImage.return_value = 0
        self.instance.UUIDString.return_value = "u-1"
        self.wvm = mock.Mock()
        volume = self.wvm.storageVolLookupByPath.return_value
        volume.info.return_value = [0, capacity, capacity]
        backing_xml = f"<backingStore><path>{backing}</path></backingStore>" if backing else ""
        volume.XMLDesc.return_value = f"<volume>{backing_xml}</volume>"
        self.pools = pools

    def get_status(self):
        return self.state

    def get_arch(self):
        return "x86_64"

    def get_dom_emulator(self):
        return "/usr/bin/qemu-kvm"

    def pool_at(self, directory):
        return Pool("src", directory) if directory in self.pools else None


def destination(*pools, shared=False, vm_here=False):
    dest = wvmInstances.__new__(wvmInstances)
    dest.wvm = mock.Mock()
    dest.wvm.listAllStoragePools.return_value = list(pools)
    if not vm_here:
        dest.wvm.lookupByUUIDString.side_effect = error(libvirt.VIR_ERR_NO_DOMAIN)
    dest.get_emulator = lambda arch: "/usr/bin/qemu-kvm"
    if isinstance(shared, Exception):
        dest.same_directory = mock.Mock(side_effect=shared)
    else:
        dest.same_directory = mock.Mock(return_value=shared)
    dest.missing_disks = mock.Mock(return_value=[])
    dest.copy_nvram = mock.Mock(return_value=None)
    dest.delete_nvram = mock.Mock()
    return dest


def migrate(dest, source, pools, **options):
    return dest.moveto(source, "vm", live=source.state == 1, unsafe=False, offline=source.state == 5,
                       uri="tcp://192.0.2.9", pools=pools, **options)


class DiskCopyTestCase(unittest.TestCase):
    def test_disks_on_shared_storage_migrate_as_before(self):
        source = Source(1, domain(disk(f"{IMAGES}/vm.qcow2")))
        dest = destination(Pool("default", IMAGES), shared=True)
        self.assertEqual(migrate(dest, source, {}), ("live", []))
        source.instance.migrate.assert_called_once()
        source.instance.migrate3.assert_not_called()

    def test_a_disk_the_destination_does_not_share_needs_a_pool(self):
        for pools, shared in (((IMAGES,), False), ((), True)):  # not shared; no pool to probe on the source
            with self.subTest(pools=pools):
                source = Source(1, domain(disk(f"{IMAGES}/vm.qcow2")), pools=pools)
                with self.assertRaisesRegex(util.OperationError, "vda .*does not share it; choose a pool"):
                    migrate(destination(Pool("default", IMAGES), shared=shared), source, {})
                source.instance.migrate.assert_not_called()

    def test_disks_are_copied_into_the_chosen_pools_under_their_new_paths(self):
        xml = domain(disk(f"{IMAGES}/vm.qcow2"), disk(f"{IMAGES}/data.raw", "vdb", fmt="raw"),
                     "<disk type='network' device='disk'><source protocol='rbd' name='p/i'/><target dev='vdc'/></disk>")
        source = Source(1, xml, inactive=xml)
        dest = destination(Pool("default", IMAGES), Pool("fast", FAST))
        mode, copied = migrate(dest, source, {"vda": "fast", "vdb": "default"})
        self.assertEqual(mode, "live, disks copied: vda to fast, vdb to default")
        self.assertEqual(copied, [f"{IMAGES}/vm.qcow2", f"{IMAGES}/data.raw"])
        params, flags = source.instance.migrate3.call_args.args[1:]
        self.assertEqual(params[libvirt.VIR_MIGRATE_PARAM_MIGRATE_DISKS], ["vda", "vdb"])
        self.assertEqual(params[libvirt.VIR_MIGRATE_PARAM_URI], "tcp://192.0.2.9")
        for key in (libvirt.VIR_MIGRATE_PARAM_DEST_XML, libvirt.VIR_MIGRATE_PARAM_PERSIST_XML):
            self.assertIn(f'<source file="{FAST}/vm.qcow2"/>', params[key])
            self.assertIn(f'<source file="{IMAGES}/data.raw"/>', params[key])
        self.assertEqual(flags & (libvirt.VIR_MIGRATE_NON_SHARED_DISK | libvirt.VIR_MIGRATE_LIVE),
                         libvirt.VIR_MIGRATE_NON_SHARED_DISK | libvirt.VIR_MIGRATE_LIVE)
        self.assertEqual(dest.missing_disks.call_args.kwargs["copied"], {f"{IMAGES}/vm.qcow2", f"{IMAGES}/data.raw"})

    def test_a_shut_off_vm_runs_paused_for_the_copy_and_is_shut_off_here(self):
        source = Source(5, domain(disk(f"{IMAGES}/vm.qcow2")))
        dest = destination(Pool("default", IMAGES), vm_here=True)
        mode, _copied = migrate(dest, source, {"vda": "default"})
        self.assertEqual(mode, "offline, disks copied: vda to default")
        dest.copy_nvram.assert_called_once_with(source)  # this host would start from the firmware's template
        source.instance.createWithFlags.assert_called_once_with(libvirt.VIR_DOMAIN_START_PAUSED)
        flags = source.instance.migrate3.call_args.args[2]
        self.assertFalse(flags & (libvirt.VIR_MIGRATE_OFFLINE | libvirt.VIR_MIGRATE_LIVE))
        dest.wvm.lookupByUUIDString.return_value.destroy.assert_called_once_with()

    def test_a_shut_off_vm_with_tpm_state_runs_paused_for_the_migration(self):
        tpm = "<tpm model='tpm-crb'><backend type='emulator' version='2.0'/></tpm>"
        source = Source(5, domain(disk(f"{IMAGES}/vm.qcow2"), tpm))
        dest = destination(Pool("default", IMAGES), shared=True, vm_here=True)
        self.assertEqual(migrate(dest, source, {}), ("offline", []))
        source.instance.createWithFlags.assert_called_once_with(libvirt.VIR_DOMAIN_START_PAUSED)
        params, flags = source.instance.migrate3.call_args.args[1:]
        # no disk is copied: they are on storage both hosts share
        self.assertNotIn(libvirt.VIR_MIGRATE_PARAM_MIGRATE_DISKS, params)
        self.assertFalse(flags & (libvirt.VIR_MIGRATE_NON_SHARED_DISK | libvirt.VIR_MIGRATE_OFFLINE))
        dest.wvm.lookupByUUIDString.return_value.destroy.assert_called_once_with()

    def test_a_shut_off_vm_with_a_saved_state_is_refused_before_it_starts(self):
        # started paused, it would resume the saved memory, then lose it
        source = Source(5, domain(disk(f"{IMAGES}/vm.qcow2")))
        source.instance.hasManagedSaveImage.return_value = 1
        with self.assertRaisesRegex(util.OperationError, "saved state"):
            migrate(destination(Pool("default", IMAGES)), source, {"vda": "default"})
        source.instance.createWithFlags.assert_not_called()

    def test_a_shut_off_vm_whose_migration_fails_is_shut_off_on_the_source_again(self):
        source = Source(5, domain(disk(f"{IMAGES}/vm.qcow2")))
        source.instance.migrate3.side_effect = libvirt.libvirtError("no route")
        dest = destination(Pool("default", IMAGES))
        dest.copy_nvram.return_value = "vm_VARS.fd"
        with self.assertRaisesRegex(libvirt.libvirtError, "no route"):
            migrate(dest, source, {"vda": "default"})
        source.instance.destroy.assert_called_once_with()
        dest.delete_nvram.assert_called_once_with("vm_VARS.fd")

    def test_a_vm_left_paused_here_is_named_but_the_migration_stands(self):
        source = Source(5, domain(disk(f"{IMAGES}/vm.qcow2")))
        dest = destination(Pool("default", IMAGES), vm_here=True)
        dest.wvm.lookupByUUIDString.return_value.destroy.side_effect = libvirt.libvirtError("busy")
        mode, _copied = migrate(dest, source, {"vda": "default"})
        self.assertEqual(mode, "offline, disks copied: vda to default, left paused here, shut it off: busy")

    def test_disks_that_cannot_be_copied_are_refused_with_their_reasons(self):
        cases = (
            (disk(f"{IMAGES}/x.iso", "vda", device="cdrom", fmt="raw"), {}, "eject it first"),
            (disk(f"{IMAGES}/vm.qcow2", extra="<readonly/>"), {}, "read-only or encrypted"),
            (disk(f"{IMAGES}/vm.vmdk", fmt="vmdk"), {}, "only raw and qcow2"),
            (disk(f"{IMAGES}/vm.qcow2"), {"backing": f"{IMAGES}/base.qcow2"}, "backing file"),
        )
        for xml, volume, reason in cases:
            with self.subTest(reason=reason):
                source = Source(1, domain(xml), **volume)
                with self.assertRaisesRegex(util.OperationError, f"cannot be migrated: vda .*{reason}"):
                    migrate(destination(Pool("default", IMAGES)), source, {"vda": "default"})
                source.instance.migrate3.assert_not_called()

    def test_a_file_of_the_same_name_in_the_pool_is_never_overwritten(self):
        source = Source(1, domain(disk(f"{IMAGES}/vm.qcow2")))
        with self.assertRaises(util.OperationError) as refused:
            migrate(destination(Pool("fast", FAST, files={"vm.qcow2"})), source, {"vda": "fast"})
        self.assertEqual(str(refused.exception), "The disks cannot be migrated: "
                         f"vda ({IMAGES}/vm.qcow2): pool fast of the destination host already has a file vm.qcow2")

    def test_only_a_pool_of_disk_files_and_a_disk_of_the_vm_can_be_chosen(self):
        source = Source(1, domain(disk(f"{IMAGES}/vm.qcow2")))
        dest = destination(Pool("vg", "/dev/vg", kind="logical"))
        with self.assertRaisesRegex(util.OperationError, "has no pool vg for disk files; vdz: the VM has no disk"):
            migrate(dest, source, {"vda": "vg", "vdz": "vg"})

    def test_each_disk_keeps_its_own_new_path(self):
        """Disks of one file name in two directories: neither copy takes the other's path."""
        xml = domain(disk(f"{IMAGES}/vm.qcow2"), disk(f"{FAST}/vm.qcow2", "vdb"))
        source = Source(1, xml, pools=(IMAGES, FAST))
        dest = destination(Pool("default", IMAGES), Pool("fast", FAST), Pool("slow", "/srv/slow"))
        migrate(dest, source, {"vda": "fast", "vdb": "slow"})
        dest_xml = source.instance.migrate3.call_args.args[1][libvirt.VIR_MIGRATE_PARAM_DEST_XML]
        self.assertIn(f'<source file="{FAST}/vm.qcow2"/><target dev="vda"/>', dest_xml)
        self.assertIn('<source file="/srv/slow/vm.qcow2"/><target dev="vdb"/>', dest_xml)

    def test_a_disk_only_the_next_start_has_must_be_shared_too(self):
        """It is neither copied nor moved: a file of its name on the
        destination would be another VM's, used at the next start."""
        source = Source(1, domain(disk(f"{IMAGES}/live.qcow2")),
                        inactive=domain(disk(f"{IMAGES}/next.qcow2")))
        with self.assertRaisesRegex(util.OperationError, f"vda \\({IMAGES}/next.qcow2\\) of the next start: "
                                                         "the destination host does not share it"):
            migrate(destination(Pool("default", IMAGES)), source, {"vda": "default"})
        source.instance.migrate3.assert_not_called()

    def test_two_copies_never_go_to_one_file(self):
        source = Source(1, domain(disk(f"{IMAGES}/vm.qcow2"), disk(f"{FAST}/vm.qcow2", "vdb")), pools=(IMAGES, FAST))
        with self.assertRaisesRegex(util.OperationError, "vdb .*another disk is copied to /srv/slow/vm.qcow2"):
            migrate(destination(Pool("slow", "/srv/slow")), source, {"vda": "slow", "vdb": "slow"})

    @staticmethod
    def fail_after_copying(source, pool, message):
        """libvirt made the copy here, then the migration failed."""
        def migrate3(*args):
            pool.files.add("vm.qcow2")
            raise libvirt.libvirtError(message)
        source.instance.migrate3.side_effect = migrate3

    def test_a_failed_migration_removes_the_partial_copies(self):
        source, pool = Source(1, domain(disk(f"{IMAGES}/vm.qcow2"))), Pool("fast", FAST)
        self.fail_after_copying(source, pool, "operation aborted: canceled by client")
        with self.assertRaisesRegex(libvirt.libvirtError, "canceled by client"):
            migrate(destination(pool), source, {"vda": "fast"})
        self.assertEqual(pool.deleted, ["vm.qcow2"])

    def test_copies_a_vm_here_uses_are_kept(self):
        source, pool = Source(1, domain(disk(f"{IMAGES}/vm.qcow2"))), Pool("fast", FAST)
        self.fail_after_copying(source, pool, "lost reply")
        with self.assertRaisesRegex(libvirt.libvirtError, "lost reply"):
            migrate(destination(pool, vm_here=True), source, {"vda": "fast"})
        self.assertEqual(pool.deleted, [])


class DiskPlanTestCase(unittest.TestCase):
    def test_each_file_disk_with_its_storage_and_reason(self):
        xml = domain(disk(f"{IMAGES}/vm.qcow2"), disk(f"{IMAGES}/x.iso", "sda", device="cdrom", fmt="raw"),
                     disk("/srv/local/data.qcow2", "vdb"))
        dest = destination(Pool("default", IMAGES), Pool("local", "/srv/local"), shared=True)
        rows = dest.disk_plan(Source(1, ""), xml)
        self.assertEqual([(r["target"], r["shared"], r["refusal"], r["capacity"]) for r in rows], [
            ("vda", True, None, 1 << 30),
            ("sda", True, "an image is not copied; eject it first", 1 << 30),
            ("vdb", False, None, 1 << 30),  # no pool on the source: cannot be told
        ])
        dest.same_directory.assert_called_once()  # one probe per directory

    def test_a_probe_that_fails_means_not_shared(self):
        dest = destination(Pool("default", IMAGES), shared=error(libvirt.VIR_ERR_SYSTEM_ERROR))
        rows = dest.disk_plan(Source(1, ""), domain(disk(f"{IMAGES}/vm.qcow2")))
        self.assertFalse(rows[0]["shared"])


class SameDirectoryTestCase(unittest.TestCase):
    def check(self, other_create):
        pool, other = mock.Mock(), mock.Mock()
        other.createXML.side_effect = other_create
        try:
            return wvmConnect.same_directory(pool, other)
        finally:
            pool.createXML.return_value.delete.assert_called_once()

    def test_a_file_the_other_host_has_already_means_one_directory(self):
        for code in (libvirt.VIR_ERR_OPERATION_INVALID, libvirt.VIR_ERR_STORAGE_VOL_EXIST):
            with self.subTest(code=code):
                self.assertTrue(self.check(error(code)))
        self.assertFalse(self.check(None))

    def test_any_other_failure_tells_nothing(self):
        with self.assertRaises(libvirt.libvirtError):
            self.check(error(libvirt.VIR_ERR_SYSTEM_ERROR))
