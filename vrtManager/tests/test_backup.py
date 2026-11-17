"""What a VM's backup holds (wvmBackup.backup_plan), the target's file
names and space, and the small files' upload read back."""

import unittest
from unittest.mock import MagicMock

import libvirt

from vrtManager import util
from vrtManager.backup import backup_file_names, check_target_space, put_file, wvmBackup
from vrtManager.instance import PERSISTENT_XML

GIB = 1024**3
QCOW = "<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='/pool/a.qcow2'/><target dev='vda'/></disk>"
RAW = "<disk type='file' device='disk'><driver name='qemu' type='raw'/><source file='/pool/b.img'/><target dev='vdb'/></disk>"
CDROM = "<disk type='file' device='cdrom'><source file='/iso/x.iso'/><target dev='sda'/></disk>"


def error(code):
    err = libvirt.libvirtError("x")
    err.err = (code,)
    return err


def domain(devices=QCOW + RAW + CDROM, os_extra=""):
    return (
        f"<domain><name>vm1</name><uuid>u</uuid><os><type>hvm</type>{os_extra}</os>"
        f"<devices>{devices}</devices></domain>"
    )


def proxy(xml=None, live=None, state=libvirt.VIR_DOMAIN_SHUTOFF, managed_save=False):
    p = wvmBackup.__new__(wvmBackup)  # no connection: only these calls
    p.wvm = MagicMock()
    p.instance = MagicMock()
    p.instance.name.return_value = "vm1"
    p.instance.state.return_value = [state, 0]
    p.instance.hasManagedSaveImage.return_value = managed_save
    persistent = xml or domain()
    p._XMLDesc = lambda flags: persistent if flags == PERSISTENT_XML else (live or persistent)
    pool = MagicMock()
    pool.name.return_value = "default"

    def volume(path):
        vol = MagicMock()
        vol.info.return_value = [0, (10 if path.endswith("qcow2") else 20) * GIB, GIB]
        vol.storagePoolLookupByVolume.return_value = pool
        return vol

    p.get_volume_by_path = MagicMock(side_effect=volume)
    return p


class BackupPlanTestCase(unittest.TestCase):
    def refused(self, p, *texts):
        with self.assertRaises(util.OperationError) as caught:
            p.backup_plan()
        for text in texts:
            self.assertIn(text, str(caught.exception))

    def test_a_vm_with_qcow2_and_raw_disks_and_a_cdrom(self):
        plan = proxy().backup_plan()
        self.assertEqual(
            plan["disks"],
            [
                {"dev": "vda", "path": "/pool/a.qcow2", "pool": "default", "format": "qcow2", "capacity": 10 * GIB},
                {"dev": "vdb", "path": "/pool/b.img", "pool": "default", "format": "raw", "capacity": 20 * GIB},
            ],
        )
        self.assertEqual(plan["left_out"], [{"dev": "sda", "why": "CD-ROM: not copied"}])
        self.assertIsNone(plan["nvram"])
        self.assertIn("<name>vm1</name>", plan["definition"])

    def test_the_nvram_is_named(self):
        xml = domain(os_extra="<nvram>/var/lib/libvirt/qemu/nvram/vm1_VARS.fd</nvram>")
        self.assertEqual(proxy(xml).backup_plan()["nvram"], "/var/lib/libvirt/qemu/nvram/vm1_VARS.fd")
        xml = domain(os_extra="<nvram><source file='/var/lib/libvirt/qemu/nvram/vm1_VARS.fd'/></nvram>")
        self.assertEqual(proxy(xml).backup_plan()["nvram"], "/var/lib/libvirt/qemu/nvram/vm1_VARS.fd")

    def test_an_nvram_outside_libvirts_directory_is_refused(self):
        self.refused(proxy(domain(os_extra="<nvram>/srv/vm1_VARS.fd</nvram>")), "/srv/vm1_VARS.fd")

    def test_refusals_name_the_reason_and_the_device(self):
        cases = {
            "encrypted": (
                "<disk type='file' device='disk'><driver type='qcow2'/><source file='/pool/a.qcow2'>"
                "<encryption format='luks'/></source><target dev='vda'/></disk>",
                ("vda", "encrypted"),
            ),
            "block": ("<disk type='block' device='disk'><source dev='/dev/sdb'/><target dev='vda'/></disk>", ("vda", "not a file")),
            "network": ("<disk type='network' device='disk'><source protocol='rbd' name='p/i'/><target dev='vda'/></disk>", ("vda", "not a file")),
            "volume": ("<disk type='volume' device='disk'><source pool='p' volume='v'/><target dev='vda'/></disk>", ("vda", "not a file")),
            "dir": ("<disk type='dir' device='disk'><source dir='/srv'/><target dev='vda'/></disk>", ("vda", "not a file")),
            "shareable": (
                "<disk type='file' device='disk'><driver type='raw'/><source file='/pool/b.img'/><target dev='vda'/><shareable/></disk>",
                ("vda", "shareable"),
            ),
            "other format": (
                "<disk type='file' device='disk'><driver type='vmdk'/><source file='/pool/c.vmdk'/><target dev='vda'/></disk>",
                ("vda", "vmdk"),
            ),
            "filesystem": (QCOW + "<filesystem type='mount'><source dir='/srv'/><target dir='t'/></filesystem>", ("host directory",)),
            "host device": (QCOW + "<hostdev mode='subsystem' type='pci'/>", ("host device",)),
            "host device NIC": (QCOW + "<interface type='hostdev'><mac address='52:54:00:00:00:09'/></interface>",
                                ("host device",)),
            "tpm": (QCOW + "<tpm model='tpm-crb'><backend type='emulator'/></tpm>", ("vm1", "TPM")),
        }
        for name, (devices, texts) in cases.items():
            with self.subTest(name):
                self.refused(proxy(domain(devices)), *texts)
        for tag in ("kernel", "initrd", "dtb"):
            with self.subTest(tag):
                self.refused(proxy(domain(os_extra=f"<{tag}>/boot/x</{tag}>")), "kernel")

    def test_a_saved_state_is_refused(self):
        self.refused(proxy(managed_save=True), "saved state")

    def test_a_disk_in_no_pool_is_refused_by_name(self):
        p = proxy()
        p.get_volume_by_path.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        self.refused(p, "vda", "/pool/a.qcow2", "no storage pool")

    def test_another_lookup_error_is_raised(self):
        p = proxy()
        p.get_volume_by_path.side_effect = error(libvirt.VIR_ERR_INTERNAL_ERROR)
        with self.assertRaises(libvirt.libvirtError):
            p.backup_plan()

    def test_live_and_persistent_disks_must_match(self):
        changed = QCOW.replace("/pool/a.qcow2", "/pool/new.qcow2") + RAW
        p = proxy(domain(changed), live=domain(), state=libvirt.VIR_DOMAIN_RUNNING)
        self.refused(p, "vda", "next start")
        p = proxy(domain(QCOW), live=domain(QCOW + RAW), state=libvirt.VIR_DOMAIN_RUNNING)
        self.refused(p, "next start")
        p = proxy(domain(), live=domain(), state=libvirt.VIR_DOMAIN_RUNNING)
        self.assertEqual(len(p.backup_plan()["disks"]), 2)


class FilesTestCase(unittest.TestCase):
    def test_file_names(self):
        uuid = "00000000-0000-4000-8000-000000000001"
        disks = [{"dev": "vda", "format": "qcow2"}, {"dev": "vdb", "format": "raw"}]
        self.assertEqual(
            backup_file_names(uuid, disks, nvram=True),
            {
                "disks": {"vda": f"wvc-{uuid}-vda.qcow2", "vdb": f"wvc-{uuid}-vdb.raw"},
                "nvram": f"wvc-{uuid}-nvram.fd",
                "domain": f"wvc-{uuid}-domain.xml",
                "manifest": f"wvc-{uuid}-manifest.json",
            },
        )
        self.assertIsNone(backup_file_names(uuid, disks, nvram=False)["nvram"])

    def test_space_counts_virtual_capacity_and_the_margin(self):
        # 2 x 10 GiB plus max(10 % of it, 1 GiB) = 22 GiB
        pool = MagicMock()
        pool.name.return_value = "b1"
        disks = [{"capacity": 10 * GIB}, {"capacity": 10 * GIB}]
        pool.info.return_value = [2, 100 * GIB, 0, int(21.9 * GIB)]
        with self.assertRaisesRegex(util.OperationError, "Storage pool b1 has 21.9 GiB free; the backup needs 22.0 GiB"):
            check_target_space(pool, disks, 10, 1)
        pool.info.return_value = [2, 100 * GIB, 0, 22 * GIB]
        check_target_space(pool, disks, 10, 1)
        pool.refresh.assert_called_with(0)

    def test_put_file_refuses_a_different_read_back(self):
        conn, pool = MagicMock(), MagicMock()
        pool.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        conn.download_volume.return_value = b"other"
        with self.assertRaisesRegex(util.OperationError, "wvc-x-domain.xml"):
            put_file(conn, pool, "wvc-x-domain.xml", b"data", (107, 107))
        conn.upload_volume.return_value.delete.assert_called_once_with(0)

    def test_put_file_returns_the_sha256_and_replaces_a_volume(self):
        conn, pool = MagicMock(), MagicMock()
        old = pool.storageVolLookupByName.return_value
        conn.download_volume.return_value = b"data"
        self.assertEqual(
            put_file(conn, pool, "wvc-x-domain.xml", b"data", (107, 108)),
            "3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7",
        )
        old.delete.assert_called_once_with(0)
        # written as QEMU's user: an NFS export that squashes root refuses root's files
        conn.upload_volume.assert_called_once_with(pool, "wvc-x-domain.xml", b"data", owner=(107, 108))

    def test_upload_volume_sets_the_owner(self):
        from lxml import etree

        from vrtManager.connection import wvmConnect

        conn = wvmConnect.__new__(wvmConnect)
        conn.wvm = MagicMock()
        pool = MagicMock()
        conn.upload_volume(pool, "f", b"ab", owner=(107, 108), mode="0600")
        volume = etree.fromstring(pool.createXML.call_args.args[0])
        self.assertEqual(volume.findtext("target/permissions/owner"), "107")
        self.assertEqual(volume.findtext("target/permissions/group"), "108")
        self.assertEqual(volume.findtext("target/permissions/mode"), "0600")
        conn.upload_volume(pool, "g", b"ab")
        self.assertIsNone(etree.fromstring(pool.createXML.call_args.args[0]).find("target/permissions"))
