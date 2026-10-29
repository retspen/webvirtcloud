"""A disk moves to another storage pool of its host: a running or paused
VM's by a block copy and a pivot, a shut-off VM's by a volume copy and a
redefinition; the source file stays. Disks that cannot move are refused
before anything changes, and a failed move deletes the copy unless a
definition names it."""

import unittest
from unittest import mock

import libvirt
from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager import util
from vrtManager.instance import wvmInstance

IMAGES = "/var/lib/libvirt/images"
FAST = "/srv/fast"


def error(code, message="error"):
    err = libvirt.libvirtError(message)
    err.err = (code, 0, message, 2, None, None, None, 0, 0)
    return err


def domain(path=f"{IMAGES}/vm.qcow2", fmt="qcow2", extra=""):
    return (f"<domain><devices><disk type='file' device='disk'><driver name='qemu' type='{fmt}'/>"
            f"<source file='{path}'/><target dev='vda'/>{extra}</disk></devices></domain>")


class Pool:
    def __init__(self, files=()):
        self.files = set(files)
        self.deleted = []

    refreshes = 0

    def refresh(self, flags=0):
        self.refreshes += 1

    def storageVolLookupByName(self, name):
        if name not in self.files:
            raise error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        volume = mock.Mock()
        volume.delete.side_effect = lambda flags: self.deleted.append(name)
        return volume


def vm(state=1, xml=None, config=None, backing=None, fast=None, snapshots=0):
    """A wvmInstance of a VM in state whose vda is in IMAGES; pool fast is on FAST."""
    proxy = wvmInstance.__new__(wvmInstance)
    proxy.instance = dom = mock.Mock()
    dom.info.return_value = [state, 0, 0, 1, 0]
    dom.isPersistent.return_value = True
    dom.isActive.return_value = state != 5
    dom.snapshotNum.return_value = snapshots
    dom.hasManagedSaveImage.return_value = 0
    dom.blockJobInfo.return_value = {}
    xml = xml or domain()
    dom.XMLDesc.side_effect = lambda flags: (config or xml) if flags & libvirt.VIR_DOMAIN_XML_INACTIVE else xml
    proxy.wvm = mock.Mock()
    volume = proxy.wvm.storageVolLookupByPath.return_value
    volume.info.return_value = [0, 1 << 30, 1 << 20]
    volume.XMLDesc.return_value = f"<volume><backingStore><path>{backing}</path></backingStore></volume>" \
        if backing else "<volume/>"
    proxy.fast = fast or Pool()
    proxy.file_pools = lambda: {"fast": (proxy.fast, FAST), "default": (Pool(), IMAGES)}
    proxy.get_snapshot_jobs = lambda: []
    return proxy


class DiskMovePlanTestCase(unittest.TestCase):
    def test_a_disk_file_moves_into_another_pool(self):
        move = vm().disk_move_plan("vda", "fast")
        self.assertEqual((move["path"], move["dest"], move["format"], move["running"]),
                         (f"{IMAGES}/vm.qcow2", f"{FAST}/vm.qcow2", "qcow2", True))

    def test_refusals(self):
        cases = (
            (vm(state=4), "fast", "defined and running, paused or shut off"),
            (vm(snapshots=1), "fast", "snapshots"),
            (vm(xml=domain(extra="<readonly/>")), "fast", "only writable raw and qcow2"),
            (vm(xml=domain(fmt="vmdk")), "fast", "only writable raw and qcow2"),
            (vm(config=domain(path=f"{IMAGES}/next.qcow2")), "fast", "the same in its running and next start"),
            (vm(backing=f"{IMAGES}/base.qcow2"), "fast", "backing file"),
            (vm(), "rbd", "not an active pool of disk files"),
            (vm(), "default", "in pool default already"),
            (vm(fast=Pool(files={"vm.qcow2"})), "fast", "Pool fast already has a file vm.qcow2"),
        )
        for proxy, pool, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(util.OperationError, reason):
                    proxy.disk_move_plan("vda", pool)


class MoveDiskTestCase(unittest.TestCase):
    def test_a_running_vm_is_copied_and_pivoted(self):
        proxy = vm()
        proxy.instance.blockJobInfo.side_effect = [{"cur": 1, "end": 2}, {"cur": 2, "end": 2}]
        with mock.patch("vrtManager.instance.time.sleep"):
            proxy.move_disk(proxy.disk_move_plan("vda", "fast"))
        dev, xml, params, flags = proxy.instance.blockCopy.call_args.args
        self.assertEqual((dev, flags), ("vda", libvirt.VIR_DOMAIN_BLOCK_COPY_TRANSIENT_JOB))
        self.assertIn(f"<source file='{FAST}/vm.qcow2'/>", xml)
        proxy.instance.blockJobAbort.assert_called_once_with("vda", libvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT)
        self.assertEqual(proxy.fast.refreshes, 2)  # the plan's, and one so that the pool lists the copy

    def test_a_shut_off_vm_gets_a_copy_and_a_new_definition(self):
        proxy = vm(state=5)
        proxy.fast.createXMLFrom = mock.Mock()
        proxy.move_disk(proxy.disk_move_plan("vda", "fast"))
        volume_xml, source, flags = proxy.fast.createXMLFrom.call_args.args
        self.assertIn("<name>vm.qcow2</name><capacity>1073741824</capacity>", volume_xml)
        self.assertIn(f'<source file="{FAST}/vm.qcow2" />', proxy.wvm.defineXML.call_args.args[0])
        proxy.instance.blockCopy.assert_not_called()

    def test_a_copy_that_ends_early_is_deleted(self):
        proxy = vm()
        proxy.instance.blockJobInfo.return_value = {}  # aborted by a cancel
        move = proxy.disk_move_plan("vda", "fast")
        proxy.fast.files.add("vm.qcow2")  # libvirt made it
        with self.assertRaisesRegex(util.OperationError, "ended before it was complete"):
            proxy.move_disk(move)
        self.assertEqual(proxy.fast.deleted, ["vm.qcow2"])

    def test_a_copy_a_definition_names_is_kept(self):
        """The pivot may have happened before its reply was lost."""
        proxy = vm()
        proxy.instance.blockJobInfo.side_effect = [{"cur": 2, "end": 2}, {}]
        proxy.instance.blockJobAbort.side_effect = libvirt.libvirtError("Cannot recv data")
        move = proxy.disk_move_plan("vda", "fast")
        proxy.instance.XMLDesc.side_effect = lambda flags: domain(path=f"{FAST}/vm.qcow2")
        proxy.fast.files.add("vm.qcow2")
        with self.assertRaisesRegex(util.OperationError, f"the VM may use {FAST}/vm.qcow2 now"):
            proxy.move_disk(move)
        self.assertEqual(proxy.fast.deleted, [])

    def test_a_file_made_by_someone_else_is_never_deleted(self):
        """It appeared after the plan, and the copy failed on it."""
        proxy = vm(state=5)
        move = proxy.disk_move_plan("vda", "fast")
        proxy.fast.files.add("vm.qcow2")
        proxy.fast.createXMLFrom = mock.Mock(side_effect=error(libvirt.VIR_ERR_STORAGE_VOL_EXIST))
        with self.assertRaises(libvirt.libvirtError):
            proxy.move_disk(move)
        self.assertEqual(proxy.fast.deleted, [])
        running = vm()
        move = running.disk_move_plan("vda", "fast")
        running.fast.files.add("vm.qcow2")
        running.instance.blockCopy.side_effect = error(libvirt.VIR_ERR_OPERATION_FAILED)
        with self.assertRaises(libvirt.libvirtError):
            running.move_disk(move)
        self.assertEqual(running.fast.deleted, [])
