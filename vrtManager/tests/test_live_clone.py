"""wvmInstance's live clone primitives: the refusals, the push backup of the
copied disks into new volumes, and the clone definition both paths share."""

import unittest
from unittest.mock import MagicMock, patch

import libvirt
from lxml import etree

from vrtManager import instance as instance_module
from vrtManager import util
from vrtManager.instance import LIVE_CLONE_MIN_LIBVIRT, VIR_DOMAIN_BACKUP_BEGIN_PRESERVE_SHUTDOWN_DOMAIN, wvmInstance

GIB = 1024**3
UUID = "abababab-0000-1111-2222-333333333333"
FORM = {
    "name": "copy",
    "disk-vda": "copy-vda.qcow2",
    "clone-net-mac-0": "52:54:00:00:00:02",
    "disk_owner_uid": 107,
    "disk_owner_gid": 107,
}


def error(code):
    err = libvirt.libvirtError("x")
    err.err = (code,)
    return err


def domain(disk="<disk type='file' device='disk'><source file='/pool/src.qcow2'/><target dev='vda'/></disk>", extra=""):
    return (
        f"<domain><name>src</name><uuid>u</uuid><devices>{disk}"
        "<disk type='file' device='cdrom'><source file='/iso/x.iso'/><target dev='sda'/></disk>"
        f"<interface type='network'><mac address='52:54:00:00:00:01'/></interface>{extra}</devices></domain>"
    )


def proxy(xml=None, free=100 * GIB, capacity=10 * GIB, existing=False):
    p = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    p.wvm = MagicMock()
    p.wvm.getLibVersion.return_value = LIVE_CLONE_MIN_LIBVIRT
    p.instance = MagicMock()
    p.instance.jobInfo.return_value = [libvirt.VIR_DOMAIN_JOB_NONE] + [0] * 11
    p.get_instances = lambda: []
    p._XMLDesc = lambda flags: xml or domain()
    p.pool = MagicMock()
    p.pool.name.return_value = "default"
    p.pool.XMLDesc.return_value = "<pool><name>default</name><target><path>/pool</path></target></pool>"
    p.pool.info.return_value = [1, 200 * GIB, 100 * GIB, free]
    if not existing:
        p.pool.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
    p.vol = MagicMock()
    p.vol.info.return_value = [0, capacity, 1 * GIB]
    p.vol.XMLDesc.return_value = "<volume><target><format type='qcow2'/></target></volume>"
    p.vol.storagePoolLookupByVolume.return_value = p.pool
    p.get_volume_by_path = MagicMock(return_value=p.vol)
    return p


class LiveCloneTargetsTestCase(unittest.TestCase):
    def refused(self, p, text):
        with self.assertRaisesRegex(util.OperationError, text):
            p.live_clone_targets(FORM, 10, 5)

    def test_targets_of_the_copied_disks(self):
        p = proxy()
        self.assertEqual(
            p.live_clone_targets(FORM, 10, 5),
            [
                {
                    "dev": "vda",
                    "pool": "default",
                    "name": "copy-vda.qcow2",
                    "path": "/pool/copy-vda.qcow2",
                    "capacity": 10 * GIB,
                    "format": "qcow2",
                }
            ],
        )
        p.pool.storageVolLookupByName.assert_called_once_with("copy-vda.qcow2")

    def test_an_older_libvirt_is_refused(self):
        p = proxy()
        p.wvm.getLibVersion.return_value = 11_009_000
        self.refused(p, "^Live clone needs libvirt 11.10 or later; shut the VM down to clone it$")

    def test_a_block_disk_is_refused(self):
        p = proxy(domain("<disk type='block' device='disk'><source dev='/dev/sdb'/><target dev='vda'/></disk>"))
        self.refused(p, "vda is not a local file")

    def test_a_shareable_disk_is_refused(self):
        p = proxy(
            domain("<disk type='file' device='disk'><source file='/pool/src.qcow2'/><target dev='vda'/><shareable/></disk>")
        )
        self.refused(p, "vda is shareable")

    def test_a_tpm_is_refused(self):
        self.refused(proxy(domain(extra="<tpm model='tpm-crb'/>")), "TPM")

    def test_a_running_libvirt_job_is_refused(self):
        p = proxy()
        p.instance.jobInfo.return_value = [libvirt.VIR_DOMAIN_JOB_UNBOUNDED] + [0] * 11
        self.refused(p, "Another job is running")

    def test_an_existing_target_volume_is_refused(self):
        self.refused(proxy(existing=True), "copy-vda.qcow2 already exists in storage pool default")

    def test_a_lookup_error_other_than_missing_is_raised(self):
        p = proxy()
        p.pool.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_INTERNAL_ERROR)
        with self.assertRaises(libvirt.libvirtError):
            p.live_clone_targets(FORM, 10, 5)

    def test_a_pool_without_room_is_refused(self):
        # 10 GiB copied plus max(10% of it, 5 GiB) = 15 GiB
        self.refused(proxy(free=14 * GIB), "Storage pool default has 14.0 GiB free; the clone needs 15.0 GiB")
        self.assertEqual(len(proxy(free=15 * GIB).live_clone_targets(FORM, 10, 5)), 1)

    def test_the_percentage_counts_when_it_is_larger(self):
        # 100 GiB copied plus max(10 GiB, 5 GiB) = 110 GiB
        self.refused(proxy(free=110 * GIB - 1, capacity=100 * GIB), "the clone needs 110.0 GiB")


class BackupTestCase(unittest.TestCase):
    def test_begin_lists_only_the_targets(self):
        p = proxy()
        p.begin_clone_backup([{"dev": "vda", "path": "/pool/copy-vda.qcow2", "format": "qcow2"}])
        xml, checkpoint, flags = p.instance.backupBegin.call_args.args
        self.assertEqual(
            xml,
            "<domainbackup mode='push'><disks><disk name='vda' backup='yes' type='file'>"
            "<target file='/pool/copy-vda.qcow2'/><driver type='qcow2'/></disk></disks></domainbackup>",
        )
        self.assertIsNone(checkpoint)
        self.assertEqual(
            flags,
            libvirt.VIR_DOMAIN_BACKUP_BEGIN_REUSE_EXTERNAL | VIR_DOMAIN_BACKUP_BEGIN_PRESERVE_SHUTDOWN_DOMAIN,
        )

    def test_targets_of_the_running_backup(self):
        p = proxy()
        p.instance.backupGetXMLDesc.return_value = (
            "<domainbackup mode='push'><disks>"
            "<disk name='vda' backup='yes' type='file'><target file='/pool/a.qcow2'/></disk>"
            "<disk name='vdb' backup='yes' type='file'><target file='/pool/b.qcow2'/></disk>"
            "<disk name='sda' backup='no'/></disks></domainbackup>"
        )
        self.assertEqual(p.backup_targets(), {"/pool/a.qcow2", "/pool/b.qcow2"})

    def test_no_backup_running(self):
        p = proxy()
        p.instance.backupGetXMLDesc.side_effect = error(libvirt.VIR_ERR_NO_DOMAIN_BACKUP)
        self.assertIsNone(p.backup_targets())
        p.instance.backupGetXMLDesc.side_effect = error(libvirt.VIR_ERR_INTERNAL_ERROR)
        with self.assertRaises(libvirt.libvirtError):
            p.backup_targets()

    def test_progress(self):
        p = proxy()
        p.instance.jobStats.return_value = {
            "type": libvirt.VIR_DOMAIN_JOB_UNBOUNDED,
            "operation": libvirt.VIR_DOMAIN_JOB_OPERATION_BACKUP,
            "disk_processed": 3,
            "disk_total": 10,
        }
        self.assertEqual(p.backup_progress(), (3, 10))
        p.instance.jobStats.assert_called_once_with(0)
        p.instance.jobStats.return_value = {"type": libvirt.VIR_DOMAIN_JOB_NONE}
        self.assertIsNone(p.backup_progress())
        p.instance.jobStats.return_value = {
            "type": libvirt.VIR_DOMAIN_JOB_UNBOUNDED,
            "operation": libvirt.VIR_DOMAIN_JOB_OPERATION_MIGRATION_OUT,
        }
        self.assertIsNone(p.backup_progress())

    def test_result(self):
        p = proxy()
        backup = {"type": libvirt.VIR_DOMAIN_JOB_COMPLETED, "operation": libvirt.VIR_DOMAIN_JOB_OPERATION_BACKUP}
        p.instance.jobStats.return_value = {**backup, "success": True}
        self.assertEqual(p.backup_result(), (True, ""))
        p.instance.jobStats.assert_called_with(
            libvirt.VIR_DOMAIN_JOB_STATS_COMPLETED | libvirt.VIR_DOMAIN_JOB_STATS_KEEP_COMPLETED
        )
        p.instance.jobStats.return_value = {**backup, "success": False, "errmsg": "Operation canceled"}
        self.assertEqual(p.backup_result(), (False, "Operation canceled"))
        p.instance.jobStats.return_value = {}
        self.assertIsNone(p.backup_result())
        p.instance.jobStats.return_value = {
            "type": libvirt.VIR_DOMAIN_JOB_COMPLETED,
            "operation": libvirt.VIR_DOMAIN_JOB_OPERATION_MIGRATION_OUT,
            "success": True,
        }
        self.assertIsNone(p.backup_result())

    def test_discard_reads_the_result_without_keeping_it(self):
        p = proxy()
        p.discard_backup_result()
        p.instance.jobStats.assert_called_once_with(libvirt.VIR_DOMAIN_JOB_STATS_COMPLETED)

    def test_freeze_thaw_abort(self):
        p = proxy()
        with patch.object(instance_module, "qemuAgentCommand", return_value='{"return": {}}') as agent:
            p.fs_freeze()
        # a timed ping first, then libvirt's own freeze
        self.assertEqual(agent.call_args.args[1:], ('{"execute": "guest-ping"}', 10, 0))
        p.instance.fsFreeze.assert_called_once_with(None, 0)
        p.fs_thaw()
        p.instance.fsThaw.assert_called_once_with(None, 0)
        p.abort_backup()
        p.instance.abortJob.assert_called_once_with()

    def test_an_agent_that_does_not_answer_is_not_asked_to_freeze(self):
        # libvirt's freeze waits without a timeout; a timed freeze could end in
        # the guest after its thaw had already failed, leaving it frozen
        p = proxy()
        with patch.object(instance_module, "qemuAgentCommand",
                          side_effect=libvirt.libvirtError("guest agent didn't respond to command within '10' seconds")):
            with self.assertRaises(libvirt.libvirtError):
                p.fs_freeze()
        p.instance.fsFreeze.assert_not_called()


class CreateCloneTargetTestCase(unittest.TestCase):
    def test_an_empty_volume_at_the_source_capacity(self):
        p = proxy()
        p.wvm.storagePoolLookupByName.return_value = p.pool
        p.pool.createXML.return_value.path.return_value = "/pool/copy-vda.qcow2"
        target = {"pool": "default", "name": "copy-vda.qcow2", "capacity": 10 * GIB, "format": "qcow2"}
        self.assertEqual(p.create_clone_target(target, 107, 108), "/pool/copy-vda.qcow2")
        p.wvm.storagePoolLookupByName.assert_called_once_with("default")
        xml, flags = p.pool.createXML.call_args.args
        volume = etree.fromstring(xml)
        self.assertEqual(volume.findtext("name"), "copy-vda.qcow2")
        self.assertEqual(volume.findtext("capacity"), str(10 * GIB))
        self.assertEqual(volume.find("target/format").get("type"), "qcow2")
        self.assertEqual(volume.findtext("target/permissions/owner"), "107")
        self.assertEqual(volume.findtext("target/permissions/group"), "108")
        self.assertEqual(flags, 0)


class DefineCloneTestCase(unittest.TestCase):
    def test_the_definition_names_the_copies(self):
        p = proxy()
        p._defineXML = MagicMock()
        p._defineXML.return_value.UUIDString.return_value = UUID
        self.assertEqual(p.define_clone(FORM, UUID, {"vda": "/pool/copy-vda.qcow2"}), UUID)
        (xml,), _ = p._defineXML.call_args
        tree = etree.fromstring(xml)
        self.assertEqual(tree.findtext("name"), "copy")
        self.assertEqual(tree.findtext("uuid"), UUID)
        self.assertEqual(tree.find("devices/disk[@device='disk']/source").get("file"), "/pool/copy-vda.qcow2")
        self.assertEqual(tree.find("devices/disk[@device='cdrom']/source").get("file"), "/iso/x.iso")
        self.assertEqual(tree.find("devices/interface/mac").get("address"), "52:54:00:00:00:02")
        p.vol.storagePoolLookupByVolume.return_value.createXMLFrom.assert_not_called()

    def test_a_missing_mac_is_refused(self):
        p = proxy()
        p._defineXML = MagicMock()
        with self.assertRaisesRegex(ValueError, "No MAC address"):
            p.define_clone({**FORM, "clone-net-mac-0": ""}, UUID, {"vda": "/pool/copy-vda.qcow2"})
        p._defineXML.assert_not_called()

    def test_clone_instance_copies_then_defines(self):
        p = proxy()
        p.get_status = lambda: 5
        p.pool.createXMLFrom.return_value.path.return_value = "/pool/copy-vda.qcow2"
        p.define_clone = MagicMock(return_value=UUID)
        self.assertEqual(p.clone_instance(FORM, UUID), UUID)
        p.pool.createXMLFrom.assert_called_once()
        p.define_clone.assert_called_once_with(FORM, UUID, {"vda": "/pool/copy-vda.qcow2"})

    def test_clone_instance_checks_the_macs_before_copying(self):
        p = proxy()
        p.get_status = lambda: 5
        with self.assertRaisesRegex(ValueError, "No MAC address"):
            p.clone_instance({**FORM, "clone-net-mac-0": ""}, UUID)
        p.pool.createXMLFrom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
