"""Migration: the source definition never stays behind; a shut-off VM's
definition is moved by the app, not by libvirt's offline migration."""

import contextlib
import unittest
from unittest import mock

import libvirt
from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager import util
from vrtManager.instance import wvmInstances


def no_domain():
    error = libvirt.libvirtError("Domain not found")
    error.err = (libvirt.VIR_ERR_NO_DOMAIN,)
    return error


class FakeDomain:
    def __init__(self, xml="<domain/>", snapshots=0, saved=False, undefine_fails=False, undefine_lost=False,
                 started=False):
        self.calls = []
        self.xml = xml
        self.snapshots = snapshots
        self.saved = saved
        self.undefine_fails = undefine_fails
        self.undefine_lost = undefine_lost  # undefined, but the reply is lost
        self.started = started  # started by another client during the move
        self.undefined = None
        self.redefined = []
        self.restored_autostart = None

    def migrate(self, dconn, flags, dname, uri, bandwidth):
        self.calls.append((flags, uri))

    def name(self):
        return "vm"

    def UUIDString(self):
        return "u-1"

    inactive_xml = None  # the persistent definition, when it differs

    def XMLDesc(self, flags):
        if flags & libvirt.VIR_DOMAIN_XML_INACTIVE and self.inactive_xml:
            return self.inactive_xml
        return self.xml

    def snapshotNum(self, flags=0):
        return self.snapshots

    def hasManagedSaveImage(self, flags=0):
        return self.saved

    def undefineFlags(self, flags):
        if self.undefine_fails:
            raise libvirt.libvirtError("undefine failed")
        self.undefined = flags
        if self.undefine_lost:
            raise libvirt.libvirtError("Cannot recv data")

    def isPersistent(self):
        return self.undefined is None or bool(self.redefined)

    def isActive(self):
        if not self.started and self.undefined is not None:
            raise no_domain()  # libvirt: an undefined shut-off VM is gone
        return self.started

    def autostart(self):
        return 1

    def setAutostart(self, value):
        self.restored_autostart = value

    def connect(self):
        return self

    def defineXML(self, xml):
        self.redefined.append(xml)
        return self


def no_volume():
    error = libvirt.libvirtError("Storage volume not found")
    error.err = (libvirt.VIR_ERR_NO_STORAGE_VOL,)
    return error


class FakeVolume:
    def __init__(self, backing):
        self.backing = backing

    def XMLDesc(self, flags=0):
        if self.backing is None:
            return "<volume><target><path>x</path></target></volume>"
        return f"<volume><backingStore><path>{self.backing}</path></backingStore></volume>"


class FakePool:
    def __init__(self, host, active=True):
        self.host = host
        self.active = active

    def isActive(self):
        return self.active

    def XMLDesc(self, flags=0):
        return "<pool><target><path>/elsewhere</path></target></pool>"

    def refresh(self, flags=0):
        self.host.refreshes += 1
        self.host.volumes |= self.host.unlisted
        self.host.unlisted = set()

    def storageVolLookupByName(self, name):
        return self.host.storageVolLookupByPath(name)


class FakeHost:
    """The destination's libvirt connection. volumes: the paths its pools
    list; unlisted: files its pools show after a refresh."""

    def __init__(self, existing=(), volumes=(), unlisted=(), backing=None, inactive_pools=()):
        self.existing = set(existing)
        self.defined = []
        self.new = []
        self.volumes = set(volumes)
        self.unlisted = set(unlisted)
        self.backing = backing or {}  # path: the path of its backing file
        self.inactive_pools = set(inactive_pools)
        self.refreshes = 0

    def storageVolLookupByPath(self, path):
        if path not in self.volumes:
            raise no_volume()
        return FakeVolume(self.backing.get(path))

    def storagePoolLookupByName(self, name):
        return FakePool(self, active=name not in self.inactive_pools)

    def listAllStoragePools(self, flags=0):
        return [FakePool(self)]

    def lookup(self, key):
        if key in self.existing:
            return FakeDomain()
        raise no_domain()

    lookupByName = lookupByUUIDString = lookup

    def defineXML(self, xml):
        self.defined.append(xml)
        self.new.append(FakeDomain())
        return self.new[-1]


class FakeSource:
    def __init__(self, state, nvram=None, **domain):
        self.state = state
        self.nvram = nvram
        self.instance = FakeDomain(**domain)

    def get_nvram(self):
        return self.nvram

    reads = 0

    def get_status(self):
        self.reads += 1
        return self.state

    def get_arch(self):
        return "x86_64"

    def get_dom_emulator(self):
        return "/usr/bin/qemu-system-x86_64"


def destination(host=None):
    dest = wvmInstances.__new__(wvmInstances)
    dest.wvm = host or FakeHost()
    dest.get_emulator = lambda arch: "/usr/bin/qemu-system-x86_64"
    return dest


class MigrationFlagsTestCase(unittest.TestCase):
    def test_the_source_definition_is_always_removed(self):
        for state, live, offline in ((1, True, False), (3, False, False)):
            with self.subTest(state=state):
                source = FakeSource(state)
                destination().moveto(source, "vm", live=live, unsafe=False, offline=offline)
                flags = source.instance.calls[0][0]
                self.assertTrue(flags & libvirt.VIR_MIGRATE_UNDEFINE_SOURCE)
                self.assertTrue(flags & libvirt.VIR_MIGRATE_PERSIST_DEST)

    def test_the_migration_uri_is_passed_on(self):
        source = FakeSource(1)
        destination().moveto(source, "vm", live=True, unsafe=False, offline=False, uri="tcp://192.0.2.12")
        self.assertEqual(source.instance.calls[0][1], "tcp://192.0.2.12")
        source = FakeSource(1)
        destination().moveto(source, "vm", live=True, unsafe=False, offline=False)
        self.assertIsNone(source.instance.calls[0][1])


class ShutOffMigrationTestCase(unittest.TestCase):
    """libvirt's offline migration fails on some builds (RHEL-156800); a
    shut-off VM is only its definition, so the app moves that itself."""

    def setUp(self):
        # a libvirtError built here takes the message of an earlier real error
        # in this thread (an earlier live test) instead of its own
        libvirt.virResetLastError()

    def test_the_definition_moves_to_the_destination(self):
        host = FakeHost()
        source = FakeSource(5, xml="<domain><name>vm</name></domain>")
        destination(host).moveto(source, "vm", live=False, unsafe=False, offline=True)
        self.assertEqual(host.defined, ["<domain><name>vm</name></domain>"])
        self.assertEqual(source.instance.calls, [])
        self.assertEqual(source.instance.undefined, libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)

    def test_a_tpm_without_local_state_moves(self):
        xml = "<domain><devices><tpm model='tpm-tis'><backend type='passthrough'/></tpm></devices></domain>"
        host = FakeHost()
        destination(host).moveto(FakeSource(5, xml=xml), "vm", live=False, unsafe=False, offline=True)
        self.assertEqual(host.defined, [xml])

    def test_refused_before_anything_changes(self):
        cases = {
            "saved state": (FakeHost(), {"saved": True}),
            "same uuid on the destination": (FakeHost(existing={"u-1"}), {}),
            "same name on the destination": (FakeHost(existing={"vm"}), {}),
        }
        for case, (host, domain) in cases.items():
            with self.subTest(case=case):
                source = FakeSource(5, **domain)
                with self.assertRaises(util.OperationError):
                    destination(host).moveto(source, "vm", live=False, unsafe=False, offline=True)
                self.assertEqual(host.defined, [])
                self.assertIsNone(source.instance.undefined)

    def test_a_failed_source_undefine_removes_the_new_definition(self):
        host = FakeHost()
        source = FakeSource(5, undefine_fails=True)
        with self.assertRaises(libvirt.libvirtError):
            destination(host).moveto(source, "vm", live=False, unsafe=False, offline=True)
        self.assertIsNotNone(host.new[0].undefined)

    def test_the_destination_definition_stays_when_the_source_has_none(self):
        host = FakeHost()
        source = FakeSource(5, undefine_lost=True)
        with self.assertRaisesRegex(util.OperationError, "only on the destination"):
            destination(host).moveto(source, "vm", live=False, unsafe=False, offline=True)
        self.assertIsNone(host.new[0].undefined)

    def test_a_failed_rollback_is_reported(self):
        host = FakeHost()
        source = FakeSource(5, undefine_fails=True)
        host.defineXML = lambda xml: host.new.append(FakeDomain(undefine_fails=True)) or host.new[-1]
        with self.assertRaisesRegex(util.OperationError, "undefine failed; the VM is now defined on both hosts"):
            destination(host).moveto(source, "vm", live=False, unsafe=False, offline=True)

    def test_a_vm_started_meanwhile_stays_on_the_source(self):
        host = FakeHost()
        source = FakeSource(5, xml="<domain><name>vm</name></domain>", started=True)
        with self.assertRaisesRegex(util.OperationError, "started on the source"):
            destination(host).moveto(source, "vm", live=False, unsafe=False, offline=True)
        self.assertEqual(source.instance.redefined, ["<domain><name>vm</name></domain>"])
        self.assertEqual(source.instance.restored_autostart, 1)
        self.assertIsNotNone(host.new[0].undefined)


class MigrationModeTestCase(unittest.TestCase):
    """The state is read once; a request that does not fit it is refused
    before anything changes, and moveto names the mode it used."""

    def migrate(self, state, **request):
        source = FakeSource(state)
        options = {"live": False, "unsafe": False, "offline": False, **request}
        mode, _copied = destination().moveto(source, "vm", **options)
        return mode, source.instance.calls[0][0] if source.instance.calls else None

    def test_refused_requests(self):
        for state, request in ((1, {"offline": True}), (3, {"offline": True}),
                               (1, {"live": True, "offline": True}), (6, {}), (4, {}), (7, {}), (0, {})):
            with self.subTest(state=state, request=request):
                source = FakeSource(state)
                with self.assertRaises(util.OperationError):
                    destination().moveto(source, "vm", unsafe=False, **{"live": False, "offline": False, **request})
                self.assertEqual(source.instance.calls, [])

    def test_a_vm_with_snapshots_is_refused_in_every_state(self):
        """libvirt keeps snapshot metadata on the source host; a migration
        does not carry it, even with shared disks."""
        for state, request in ((1, {"live": True}), (1, {}), (3, {}), (5, {})):
            with self.subTest(state=state, request=request):
                host = FakeHost()
                source = FakeSource(state, snapshots=1)
                with self.assertRaisesRegex(util.OperationError, "A VM with snapshots cannot be migrated"):
                    destination(host).moveto(source, "vm", unsafe=False, **{"live": False, "offline": False, **request})
                self.assertEqual(source.instance.calls, [])
                self.assertEqual(host.defined, [])

    def test_modes(self):
        live, unsafe = libvirt.VIR_MIGRATE_LIVE, libvirt.VIR_MIGRATE_UNSAFE
        converge, compressed = libvirt.VIR_MIGRATE_AUTO_CONVERGE, libvirt.VIR_MIGRATE_COMPRESSED
        mode, flags = self.migrate(1, live=True, autoconverge=True, compress=True, unsafe=True)
        self.assertEqual(mode, "live, unsafe, auto converge, compressed")
        self.assertEqual(flags & (live | unsafe | converge | compressed), live | unsafe | converge | compressed)
        source = FakeSource(1)
        destination().moveto(source, "vm", live=True, unsafe=False, offline=False)
        self.assertEqual(source.reads, 1)
        mode, flags = self.migrate(1, compress=True, autoconverge=True)
        self.assertEqual(mode, "non-live, compressed")
        self.assertEqual(flags & (live | converge | compressed), compressed)
        # a paused VM stays paused; the tuning options are for running VMs
        mode, flags = self.migrate(3, live=True, autoconverge=True, compress=True, unsafe=True)
        self.assertEqual(mode, "live")
        self.assertEqual(flags & (live | unsafe | converge | compressed), live)
        self.assertEqual(self.migrate(5), ("offline", None))
        self.assertEqual(self.migrate(5, offline=True), ("offline", None))
        # asked while it ran, then shut down: it moves offline, the tuning options unused
        self.assertEqual(self.migrate(5, live=True, autoconverge=True, compress=True), ("offline", None))


def with_disks(*disks):
    return "<domain><devices>%s</devices></domain>" % "".join(disks)


FILE_DISK = "<disk type='file' device='disk'><source file='/pool/vm.qcow2'/><target dev='vda'/></disk>"


class DestinationDisksTestCase(unittest.TestCase):
    """Every disk of the VM must be a volume the destination knows; the
    VM is refused before anything changes otherwise, naming the disks.
    (Which disks are copied, and that the others are shared, is
    test_disk_copy_migration's.)"""

    def setUp(self):
        patcher = mock.patch.object(wvmInstances, "disk_copies", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def migrate(self, host, xml, state=1, inactive_xml=None):
        source = FakeSource(state, xml=xml)
        source.instance.inactive_xml = inactive_xml
        live = state != 5
        destination(host).moveto(source, "vm", live=live, unsafe=False, offline=not live)
        return source

    def test_known_volumes_migrate(self):
        host = FakeHost(volumes={"/pool/vm.qcow2", "/pool/base.qcow2", "/iso/os.iso"})
        xml = with_disks(
            "<disk type='file' device='disk'><source file='/pool/vm.qcow2'/><target dev='vda'/>"
            "<backingStore type='file'><source file='/pool/base.qcow2'/><backingStore/></backingStore></disk>",
            "<disk type='file' device='cdrom'><source file='/iso/os.iso'/><target dev='sda'/></disk>",
            "<disk type='file' device='cdrom'><target dev='sdb'/></disk>",  # empty
            "<disk type='network' device='disk'><source protocol='rbd' name='rbd/vm'/><target dev='vdb'/></disk>",
            "<disk type='volume' device='disk'><source pool='p' volume='/pool/vm.qcow2'/><target dev='vdc'/></disk>",
        )
        self.assertEqual(len(self.migrate(host, xml).instance.calls), 1)
        self.assertEqual(host.defined, [])
        self.migrate(host, xml, state=5)
        self.assertEqual(len(host.defined), 1)

    def test_missing_disks_are_refused_and_named(self):
        cases = {
            "vda \\(/pool/vm.qcow2\\)": with_disks(FILE_DISK),
            "sda \\(/iso/os.iso\\)": with_disks(
                "<disk type='file' device='cdrom'><source file='/iso/os.iso'/><target dev='sda'/></disk>"),
            "vda \\(/pool/base.qcow2\\)": with_disks(
                "<disk type='file' device='disk'><source file='/pool/vm.qcow2'/><target dev='vda'/>"
                "<backingStore type='file'><source file='/pool/base.qcow2'/></backingStore></disk>"),
            "vdb \\(/dev/sdz\\)": with_disks(
                "<disk type='block' device='disk'><source dev='/dev/sdz'/><target dev='vdb'/></disk>"),
            "vdc \\(p/v\\)": with_disks(
                "<disk type='volume' device='disk'><source pool='p' volume='v'/><target dev='vdc'/></disk>"),
        }
        for missing, xml in cases.items():
            for state in (1, 5):
                with self.subTest(missing=missing, state=state):
                    host = FakeHost(volumes=set() if "vm.qcow2" in missing else {"/pool/vm.qcow2"})
                    source = FakeSource(state, xml=xml)
                    with self.assertRaisesRegex(util.OperationError, missing):
                        destination(host).moveto(source, "vm", live=state == 1, unsafe=False, offline=state == 5)
                    self.assertEqual((source.instance.calls, host.defined), ([], []))

    def test_a_disk_of_the_persistent_definition_is_checked_too(self):
        host = FakeHost(volumes={"/pool/vm.qcow2"})
        inactive = with_disks(FILE_DISK, "<disk type='file' device='disk'><source file='/pool/data.img'/>"
                                         "<target dev='vdb'/></disk>")
        with self.assertRaisesRegex(util.OperationError, "vdb \\(/pool/data.img\\)"):
            self.migrate(host, with_disks(FILE_DISK), inactive_xml=inactive)

    def test_pools_are_refreshed_before_a_disk_counts_as_missing(self):
        # a file another host made on shared storage is listed after a refresh
        host = FakeHost(unlisted={"/pool/vm.qcow2"})
        self.assertEqual(len(self.migrate(host, with_disks(FILE_DISK)).instance.calls), 1)
        self.assertEqual(host.refreshes, 1)
        host = FakeHost(volumes={"/pool/vm.qcow2"})
        self.migrate(host, with_disks(FILE_DISK))
        self.assertEqual(host.refreshes, 0)

    def test_backing_files_the_definition_does_not_list_are_checked(self):
        # an inactive definition has no <backingStore>: the volume tells
        for state in (1, 5):
            with self.subTest(state=state):
                host = FakeHost(volumes={"/pool/vm.qcow2", "/pool/mid.qcow2"},
                                backing={"/pool/vm.qcow2": "/pool/mid.qcow2", "/pool/mid.qcow2": "/local/base.qcow2"})
                with self.assertRaisesRegex(util.OperationError, "vda \\(/local/base.qcow2\\)"):
                    self.migrate(host, with_disks(FILE_DISK), state=state)
                host.volumes.add("/local/base.qcow2")
                self.migrate(host, with_disks(FILE_DISK), state=state)

    def test_a_network_backing_image_is_not_checked(self):
        host = FakeHost(volumes={"/pool/vm.qcow2"}, backing={"/pool/vm.qcow2": "nbd://storage.example.org:10809/base"})
        self.assertEqual(len(self.migrate(host, with_disks(FILE_DISK)).instance.calls), 1)

    def test_disks_that_cannot_be_checked_are_refused(self):
        xml = with_disks("<disk type='dir' device='disk'><source dir='/srv/vm'/><target dev='vdb'/></disk>")
        with self.assertRaisesRegex(util.OperationError, "vdb \\(dir disk, cannot be checked\\)"):
            self.migrate(FakeHost(), xml, state=5)

    def test_a_volume_of_an_inactive_pool_is_missing(self):
        host = FakeHost(volumes={"v"}, inactive_pools={"p"})
        xml = with_disks("<disk type='volume' device='disk'><source pool='p' volume='v'/><target dev='vdc'/></disk>")
        with self.assertRaisesRegex(util.OperationError, "vdc \\(p/v\\)"):
            self.migrate(host, xml)


class NvramCopyTestCase(unittest.TestCase):
    """A shut-off move copies the UEFI variables file to the destination."""

    PATH = "/var/lib/libvirt/qemu/nvram/vm_VARS.fd"

    def setUp(self):
        libvirt.virResetLastError()  # see ShutOffMigrationTestCase.setUp
        self.source = FakeSource(5, nvram=self.PATH, xml="<domain><name>vm</name></domain>")
        self.source.wvm = mock.MagicMock()
        self.source.wvm.newStream.return_value.recvAll.side_effect = lambda fn, out: fn(None, b"vars", out)
        self.source_pool = mock.MagicMock()
        self.source._nvram_pool = lambda: contextlib.nullcontext(self.source_pool)
        self.host = FakeHost()
        self.dest = destination(self.host)
        self.dest_pool = mock.MagicMock()
        self.dest._nvram_pool = lambda: contextlib.nullcontext(self.dest_pool)
        self.dest.wvm.newStream = mock.MagicMock()
        self.shared = mock.patch.object(wvmInstances, "same_directory", return_value=False)
        self.shared.start()
        self.addCleanup(self.shared.stop)

    def move(self):
        self.dest.moveto(self.source, "vm", live=False, unsafe=False, offline=True)

    def test_the_file_is_copied_before_the_definition(self):
        self.move()
        copy = self.dest_pool.createXML.return_value
        self.assertIn("<name>vm_VARS.fd</name><capacity>4</capacity>", self.dest_pool.createXML.call_args[0][0])
        copy.upload.assert_called_once_with(self.dest.wvm.newStream.return_value, 0, 4, 0)
        self.assertEqual(self.host.defined, ["<domain><name>vm</name></domain>"])

    def test_a_shared_directory_is_not_copied(self):
        self.shared.stop()
        with mock.patch.object(wvmInstances, "same_directory", return_value=True):
            self.move()
        self.dest_pool.createXML.assert_not_called()
        self.shared.start()

    def test_a_directory_whose_sharing_cannot_be_told_stops_the_move(self):
        self.shared.stop()
        with mock.patch.object(wvmInstances, "same_directory", side_effect=libvirt.libvirtError("no marker")):
            with self.assertRaisesRegex(libvirt.libvirtError, "no marker"):
                self.move()
        self.shared.start()
        self.assertEqual(self.host.defined, [])

    def test_the_copy_is_deleted_when_the_definition_fails(self):
        # the raised error is this one: its message can be another libvirt
        # error the thread recorded (a closed connection of an earlier live test)
        error = libvirt.libvirtError("define failed")
        self.host.defineXML = mock.MagicMock(side_effect=error)
        with self.assertRaises(libvirt.libvirtError) as raised:
            self.move()
        self.assertIs(raised.exception, error)
        self.dest_pool.storageVolLookupByName.assert_called_once_with("vm_VARS.fd")
        self.dest_pool.storageVolLookupByName.return_value.delete.assert_called_once_with(0)


class MigrationPlanTestCase(unittest.TestCase):
    """The Migrate tab's plan: the pools each disk can be copied into, and the
    next start's disks the migration does not carry."""

    def test_pools_with_a_file_of_the_name_and_the_next_start_disks(self):
        dest = wvmInstances.__new__(wvmInstances)
        pools = {"default": (mock.MagicMock(), "/i"), "fast": (mock.MagicMock(), "/srv/fast"),
                 "slow": (mock.MagicMock(), "/srv/slow")}
        dest.file_pools = lambda: pools
        vda = {"target": "vda", "path": "/i/vm.qcow2", "shared": False, "refusal": None}
        vdb = {"target": "vdb", "path": "/i/new.qcow2", "shared": False, "refusal": None}
        dest.disk_plan = lambda conn, xml: [dict(row) for row in {"live": [vda], "next": [vda, vdb]}[xml]]
        # the pool on the disk's directory has a file of its name
        dest._find_volume = lambda pool, name: object() if pool is pools["default"][0] else None
        disks, pending = dest.migration_plan(None, "live", "next")
        self.assertEqual((disks[0]["free_pools"], disks[0]["default"]), (["fast", "slow"], "fast"))
        self.assertEqual(pending, [vdb])
        for pool, directory in pools.values():
            pool.refresh.assert_called_once_with(0)  # a file made since is seen
