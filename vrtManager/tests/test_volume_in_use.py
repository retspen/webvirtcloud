"""A volume a VM still needs is never deleted from a storage pool: not a
disk, not a backing file, not a file of a snapshot. libvirt deletes any
volume it is asked to; the live cases are in instances/tests/test_live_dataloss.py."""

import unittest
from unittest.mock import MagicMock

import libvirt
from libvirt import libvirtError

from vrtManager import util
from vrtManager.storage import wvmStorage


def domain(uuid, disks=(), snapshots=()):
    dom = MagicMock()
    dom.UUIDString.return_value = uuid
    dom.hasManagedSaveImage.return_value = 0
    devices = "".join(f"<disk type='file' device='disk'><source file='{d}'/></disk>" for d in disks)
    dom.XMLDesc.return_value = f"<domain><devices>{devices}</devices></domain>"
    snaps = []
    for xml in snapshots:
        snap = MagicMock()
        snap.getXMLDesc.return_value = xml
        snaps.append(snap)
    dom.listAllSnapshots.return_value = snaps
    return dom


def volume(path, backing=None):
    vol = MagicMock()
    vol.path.return_value = path
    parent = f"<backingStore><path>{backing}</path></backingStore>" if backing else ""
    vol.XMLDesc.return_value = f"<volume>{parent}</volume>"
    return vol


def storage(domains=(), volumes=()):
    conn = wvmStorage.__new__(wvmStorage)
    conn.wvm = MagicMock()
    conn.wvm.listAllDomains.return_value = list(domains)
    pool = MagicMock(**{"isActive.return_value": True})
    pool.listAllVolumes.return_value = list(volumes)
    by_name = {v.path().rsplit("/", 1)[1]: v for v in volumes}
    pool.storageVolLookupByName.side_effect = lambda name: by_name[name]
    conn.wvm.listAllStoragePools.return_value = [pool]
    conn.pool = pool
    return conn, by_name


SNAPSHOT = (
    "<domainsnapshot><name>s</name><memory snapshot='external' file='/pool/vm.s.mem'/>"
    "<disks><disk name='vda' snapshot='external'><source file='/pool/vm.s'/></disk></disks>"
    "<domain><devices><disk type='file' device='disk'><source file='/pool/vm.qcow2'/></disk></devices></domain>"
    "</domainsnapshot>"
)


class PathsInUseTestCase(unittest.TestCase):
    def test_disks_backing_files_and_snapshot_files_are_in_use(self):
        conn, _ = storage(
            domains=[domain("u1", ["/pool/vm.now"], [SNAPSHOT])],
            volumes=[volume("/pool/clone.qcow2", backing="/pool/template.qcow2")],
        )
        self.assertEqual(
            conn.paths_in_use(),
            {"/pool/vm.now", "/pool/vm.s", "/pool/vm.s.mem", "/pool/vm.qcow2", "/pool/template.qcow2"},
        )

    def test_a_disk_detached_since_the_vm_was_saved_is_in_use(self):
        dom = domain("u1", ["/pool/vm.qcow2"])
        dom.hasManagedSaveImage.return_value = 1
        dom.managedSaveGetXMLDesc.return_value = (
            "<domain><devices><disk type='file' device='disk'><source file='/pool/vm.qcow2'/></disk>"
            "<disk type='file' device='disk'><source file='/pool/data.qcow2'/></disk></devices></domain>")
        conn, _ = storage(domains=[dom])
        self.assertEqual(conn.paths_in_use(), {"/pool/vm.qcow2", "/pool/data.qcow2"})

    def test_a_saved_state_gone_meanwhile_counts_the_disks_the_vm_started_with(self):
        dom = domain("u1", ["/pool/vm.qcow2"])
        dom.hasManagedSaveImage.return_value = 1
        error = libvirtError("no saved state")
        error.get_error_code = lambda: libvirt.VIR_ERR_OPERATION_INVALID
        dom.managedSaveGetXMLDesc.side_effect = error
        conn, _ = storage(domains=[dom])
        self.assertEqual(conn.paths_in_use(), {"/pool/vm.qcow2"})
        self.assertEqual(dom.XMLDesc.call_args_list[-1].args, (0,))
        # a VM removed meanwhile uses nothing
        error.get_error_code = lambda: libvirt.VIR_ERR_NO_DOMAIN
        dom.XMLDesc.reset_mock()
        self.assertEqual(conn.paths_in_use(), {"/pool/vm.qcow2"})
        self.assertEqual(dom.XMLDesc.call_count, 2)

    def test_one_domain_and_the_backing_files_of_own_volumes_can_be_left_out(self):
        conn, _ = storage(
            domains=[domain("u1", ["/pool/a.qcow2"]), domain("u2", ["/pool/b.qcow2"])],
            volumes=[volume("/pool/a.qcow2", backing="/pool/base.qcow2")],
        )
        self.assertEqual(conn.paths_in_use(skip_uuid="u1", own=["/pool/a.qcow2"]), {"/pool/b.qcow2"})


    def test_a_network_disk_is_in_use_by_its_name(self):
        dom = domain("u1")
        dom.XMLDesc.return_value = (
            "<domain><devices><disk type='network' device='disk'>"
            "<source protocol='rbd' name='rbdpool/disk'/></disk></devices></domain>"
        )
        conn, _ = storage(domains=[dom])
        self.assertIn("rbdpool/disk", conn.paths_in_use())

    def test_a_pool_volume_disk_is_in_use_by_its_path(self):
        for xml in (
            "<domain><devices>{}</devices></domain>",
            "<domain/>",  # in a snapshot's saved definition
        ):
            with self.subTest(xml):
                disk = "<disk type='volume' device='disk'><source pool='default' volume='disk.qcow2'/></disk>"
                dom = domain("u1")
                if "{}" in xml:
                    dom.XMLDesc.return_value = xml.format(disk)
                else:
                    snap = MagicMock()
                    snap.getXMLDesc.return_value = f"<domainsnapshot><domain><devices>{disk}</devices></domain></domainsnapshot>"
                    dom.listAllSnapshots.return_value = [snap]
                conn, _ = storage(domains=[dom], volumes=[volume("/pool/disk.qcow2")])
                conn.wvm.storagePoolLookupByName.return_value = conn.pool
                self.assertIn("/pool/disk.qcow2", conn.paths_in_use())

    def test_a_disk_not_running_in_an_inactive_pool_is_refused(self):
        # its overlay's backing file is in the volume's XML, which an inactive pool does not give
        inactive = MagicMock(**{"isActive.return_value": False, "name.return_value": "overlays",
                                "XMLDesc.return_value": "<pool><target><path>/overlays</path></target></pool>"})
        overlay = "<disk type='file' device='disk'><source file='/overlays/b.qcow2'/></disk>"
        raw = "<disk type='file' device='disk'><driver type='raw'/><source file='/overlays/b.qcow2'/></disk>"
        other = "<disk type='file' device='disk'><source file='/overlays-2/b.qcow2'/></disk>"

        def check(live, config, active, refused, saved=None):
            dom = domain("u1")
            dom.XMLDesc.side_effect = lambda flags: f"<domain><devices>{config if flags else live}</devices></domain>"
            dom.isActive.return_value = active
            if saved:
                dom.hasManagedSaveImage.return_value = 1
                dom.managedSaveGetXMLDesc.return_value = f"<domain><devices>{saved}</devices></domain>"
            conn, _ = storage(domains=[dom])
            conn.wvm.listAllStoragePools.return_value = [conn.pool, inactive]
            if refused:
                with self.assertRaisesRegex(util.InUse, "Pool overlays is not active"):
                    conn.paths_in_use()
            else:
                conn.paths_in_use()  # answers

        for case, args in (("stopped", (overlay, overlay, False, True)),
                           ("running: the live definition has the chain", (overlay, overlay, True, False)),
                           ("the next start's disk", ("", overlay, True, True)),
                           ("a raw disk grows from nothing", (raw, raw, False, False)),
                           ("another directory", (other, other, False, False))):
            with self.subTest(case):
                check(*args)
        with self.subTest("a saved state's disk"):
            check("", "", False, True, saved=overlay)

    def test_a_volume_that_cannot_be_read_is_not_taken_as_unused(self):
        removed, unreadable = volume("/pool/gone.qcow2"), volume("/pool/top.qcow2")
        error = libvirtError("removed")
        error.err = (libvirt.VIR_ERR_NO_STORAGE_VOL,)
        removed.XMLDesc.side_effect = error
        conn, _ = storage(volumes=[removed])
        self.assertEqual(conn.paths_in_use(), set())
        unreadable.XMLDesc.side_effect = libvirtError("permission denied")
        conn, _ = storage(volumes=[unreadable])
        with self.assertRaises(libvirtError):
            conn.paths_in_use()


class DeleteVolumeTestCase(unittest.TestCase):
    def test_a_volume_in_use_is_refused(self):
        for case, domains, volumes in (
            ("disk", [domain("u1", ["/pool/disk.qcow2"])], [volume("/pool/disk.qcow2")]),
            ("backing file", [], [volume("/pool/disk.qcow2"), volume("/pool/top.qcow2", backing="/pool/disk.qcow2")]),
            ("snapshot point", [domain("u1", ["/pool/vm.s"], [SNAPSHOT.replace("vm.qcow2", "disk.qcow2")])],
             [volume("/pool/disk.qcow2")]),
        ):
            with self.subTest(case):
                conn, vols = storage(domains, volumes)
                with self.assertRaisesRegex(util.OperationError, "disk.qcow2 is in use"):
                    conn.del_volume("disk.qcow2")
                vols["disk.qcow2"].delete.assert_not_called()

    def test_an_unused_volume_is_deleted(self):
        conn, vols = storage([domain("u1", ["/pool/other.qcow2"])], [volume("/pool/disk.qcow2")])
        conn.del_volume("disk.qcow2")
        vols["disk.qcow2"].delete.assert_called_once_with(0)


class RunningCopyTestCase(unittest.TestCase):
    """A running guest's disk is not copied: the copy would mix instants."""

    def test_each_way_a_disk_names_the_volume_refuses_its_copy(self):
        for source in ("file='/pool/disk.qcow2'", "dev='/pool/disk.qcow2'", "protocol='rbd' name='/pool/disk.qcow2'",
                       "pool='pool' volume='disk.qcow2'"):
            with self.subTest(source=source):
                dom = MagicMock(**{"name.return_value": "vm"})
                dom.XMLDesc.return_value = f"<domain><devices><disk device='disk'><source {source}/></disk></devices></domain>"
                conn, _ = storage([dom], [volume("/pool/disk.qcow2")])
                conn.pool.name.return_value = "pool"
                with self.assertRaisesRegex(util.OperationError, "The running VMs vm use volume disk.qcow2"):
                    conn.refuse_running_copy("disk.qcow2")
                conn.wvm.listAllDomains.assert_called_once_with(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)

    def test_another_disk_does_not(self):
        conn, _ = storage([domain("u1", ["/pool/other.qcow2"])], [volume("/pool/disk.qcow2")])
        conn.pool.name.return_value = "pool"
        conn.refuse_running_copy("disk.qcow2")
