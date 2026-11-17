"""What a VM's backup holds (wvmBackup.backup_plan), the target's file
names and space, and the small files' upload read back."""

import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock

import libvirt

from vrtManager import util
from vrtManager.backup import backup_file_names, check_target_space, put_file, wvmBackup
from vrtManager.instance import PERSISTENT_XML

GIB = 1024**3
QCOW = "<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='/pool/a.qcow2'/><target dev='vda'/></disk>"
RAW = "<disk type='file' device='disk'><driver name='qemu' type='raw'/><source file='/pool/b.img'/><target dev='vdb'/></disk>"
TPM = "<tpm model='tpm-crb'><backend type='emulator' version='2.0'/></tpm>"
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
    p.instance.UUIDString.return_value = "u"
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
            "encrypted tpm": (QCOW + "<tpm model='tpm-crb'><backend type='emulator' version='2.0'>"
                              "<encryption secret='33333333-3333-4333-8333-333333333333'/></backend></tpm>", ("vm1", "TPM")),
            "tpm state path": (QCOW + "<tpm model='tpm-crb'><backend type='emulator' version='2.0'>"
                               "<source type='dir' path='/srv/tpm'/></backend></tpm>", ("vm1", "TPM")),
            "host tpm": (QCOW + "<tpm model='tpm-tis'><backend type='passthrough'><device path='/dev/tpm0'/></backend></tpm>",
                         ("vm1", "TPM")),
        }
        for name, (devices, texts) in cases.items():
            with self.subTest(name):
                self.refused(proxy(domain(devices)), *texts)
        for tag in ("kernel", "initrd", "dtb"):
            with self.subTest(tag):
                self.refused(proxy(domain(os_extra=f"<{tag}>/boot/x</{tag}>")), "kernel")

    def test_a_shut_off_vms_tpm_is_backed_up_and_its_state_read_by_the_job(self):
        p = proxy(domain(QCOW + TPM))
        p._tpm_pool = MagicMock()
        self.assertTrue(p.backup_plan()["tpm"])
        p._tpm_pool.assert_not_called()  # the plan runs in pages too: only the worker reads the state
        self.assertFalse(proxy(domain(QCOW)).backup_plan()["tpm"])

    def test_the_tpm_state_files_are_read_without_swtpms_lock(self):
        p = proxy(domain(QCOW + TPM))
        state = MagicMock()
        state.listVolumes.return_value = [".lock", "tpm2-00.permall"]
        p._tpm_pool = MagicMock(return_value=nullcontext(state))
        p.download_volume = MagicMock(return_value=b"state")
        self.assertEqual(p.read_tpm(), {"tpm2-00.permall": b"state"})
        p._tpm_pool.assert_called_once_with("u")
        state.storageVolLookupByName.assert_called_once_with("tpm2-00.permall")

    def test_a_tpm_that_never_started_has_no_files(self):
        p = proxy(domain(QCOW + TPM))
        p._tpm_pool = MagicMock(return_value=nullcontext(None))
        self.assertEqual(p.read_tpm(), {})

    def test_a_running_or_paused_vm_with_a_tpm_is_refused(self):
        for state in (libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED):
            with self.subTest(state):
                self.refused(proxy(domain(QCOW + TPM), state=state), "vm1", "TPM", "shut it down")

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
                "tpm": f"wvc-{uuid}-tpm-",
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
        conn.upload_volume.assert_called_once_with(pool, "wvc-x-domain.xml", b"data", owner=(107, 108), mode="0644")

    def test_a_tpm_directory_that_does_not_exist_gives_no_pool(self):
        import errno

        from vrtManager.connection import wvmConnect

        conn = wvmConnect.__new__(wvmConnect)
        conn.wvm = MagicMock()
        missing = libvirt.libvirtError("cannot open directory")
        missing.err = (libvirt.VIR_ERR_SYSTEM_ERROR, 0, "", 2, None, None, None, errno.ENOENT, -1)
        conn.wvm.storagePoolCreateXML.side_effect = missing
        conn.wvm.listAllStoragePools.return_value = []
        with conn._tpm_pool("u") as pool:
            self.assertIsNone(pool)
        self.assertIn("/var/lib/libvirt/swtpm/u/tpm2", conn.wvm.storagePoolCreateXML.call_args.args[0])
        conn.wvm.listAllStoragePools.return_value = []
        with self.assertRaises(libvirt.libvirtError), conn._tpm_pool("u", build=True):
            pass
        missing.err = (libvirt.VIR_ERR_SYSTEM_ERROR, 0, "", 2, None, None, None, errno.EACCES, -1)
        with self.assertRaises(libvirt.libvirtError), conn._tpm_pool("u"):
            pass

    def test_a_tpm_pool_a_stopped_worker_left_is_taken_and_destroyed(self):
        from vrtManager.connection import wvmConnect

        conn = wvmConnect.__new__(wvmConnect)
        conn.wvm = MagicMock()
        left = MagicMock()
        left.XMLDesc.return_value = "<pool><target><path>/var/lib/libvirt/swtpm/u/tpm2</path></target></pool>"
        conn.wvm.listAllStoragePools.return_value = [left]
        with conn._tpm_pool("u") as pool:
            self.assertIs(pool, left)
        conn.wvm.storagePoolCreateXML.assert_not_called()
        left.refresh.assert_called_once_with(0)
        left.destroy.assert_called_once_with()

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


SOURCE = """<domain type='kvm'>
  <name>vm1</name><uuid>11111111-1111-4111-8111-111111111111</uuid><genid>22222222-2222-4222-8222-222222222222</genid>
  <title>web</title>
  <sysinfo type='smbios'><system><entry name='uuid'>11111111-1111-4111-8111-111111111111</entry></system></sysinfo>
  <os><type arch='x86_64' machine='pc-q35-10.1'>hvm</type><loader readonly='yes' type='pflash'>/usr/share/edk2/ovmf/OVMF_CODE.fd</loader>
    <nvram>/var/lib/libvirt/qemu/nvram/vm1_VARS.fd</nvram></os>
  <devices>
    <emulator>/usr/libexec/qemu-kvm</emulator>
    <disk type='file' device='disk'><driver name='qemu' type='qcow2'/>
      <source file='/pool/a.qcow2'><seclabel model='dac' relabel='no'/></source>
      <backingStore type='file'><format type='qcow2'/><source file='/pool/base.qcow2'/></backingStore>
      <target dev='vda' bus='virtio'/></disk>
    <disk type='file' device='disk'><driver name='qemu' type='raw'/><source file='/pool/b.img'/><target dev='vdb' bus='virtio'/></disk>
    <disk type='file' device='cdrom'><source file='/iso/cidata-11111111-1111-4111-8111-111111111111.iso'/><target dev='sda'/></disk>
    <disk type='file' device='cdrom'><source file='/iso/install.iso'/><target dev='sdb'/></disk>
    <disk type='file' device='floppy'><source file='/iso/drivers.vfd'/><target dev='fda'/></disk>
    <interface type='network'><mac address='52:54:00:00:00:01'/><source network='default'/>
      <filterref filter='clean-traffic'><parameter name='MAC' value='52:54:00:00:00:01'/><parameter name='IP' value='192.0.2.5'/></filterref></interface>
    <interface type='bridge'><mac address='52:54:00:00:00:02'/><source bridge='br0'/><link state='up'/></interface>
    <graphics type='vnc' passwd='secret1'/>
  </devices>
</domain>"""


class RestoreDefinitionTestCase(unittest.TestCase):
    def restored(self, connect=False):
        from lxml import etree

        from vrtManager.backup import restore_definition

        xml = restore_definition(
            SOURCE, name="vm1-restored", uuid="33333333-3333-4333-8333-333333333333",
            macs=["52:54:00:aa:00:01", "52:54:00:aa:00:02"],
            disks={"vda": ("/dest/vm1-restored-vda.qcow2", "qcow2"), "vdb": ("/dest/vm1-restored-vdb.raw", "raw")},
            nvram="/var/lib/libvirt/qemu/nvram/vm1-restored_VARS.fd", connect=connect,
        )
        return etree.fromstring(xml)

    def test_restore_definition(self):
        tree = self.restored()
        self.assertEqual(tree.findtext("name"), "vm1-restored")
        self.assertEqual(tree.findtext("uuid"), "33333333-3333-4333-8333-333333333333")
        self.assertEqual(tree.xpath("string(sysinfo/system/entry[@name='uuid'])"), "33333333-3333-4333-8333-333333333333")
        self.assertEqual(tree.findtext("genid") or "", "")  # libvirt makes a new one
        self.assertIsNotNone(tree.find("genid"))
        self.assertEqual(tree.xpath("devices/interface/mac/@address"), ["52:54:00:aa:00:01", "52:54:00:aa:00:02"])
        self.assertEqual(tree.xpath("devices/interface/filterref/parameter[@name='MAC']/@value"), ["52:54:00:aa:00:01"])
        self.assertEqual(tree.xpath("devices/interface/filterref/parameter[@name='IP']"), [])
        self.assertEqual(tree.xpath("devices/disk[@device='disk']/source/@file"),
                         ["/dest/vm1-restored-vda.qcow2", "/dest/vm1-restored-vdb.raw"])
        self.assertEqual(tree.xpath("devices/disk[@device='disk']/driver/@type"), ["qcow2", "raw"])
        self.assertEqual(tree.xpath("devices/disk//backingStore|devices/disk//seclabel|devices/disk//dataStore"), [])
        self.assertEqual(tree.xpath("devices/disk[@device='cdrom']/source"), [])  # the old VM's cloud-init seed
        self.assertEqual(len(tree.xpath("devices/disk[@device='cdrom']")), 2)  # the drives stay
        self.assertEqual(tree.findtext("os/nvram"), "/var/lib/libvirt/qemu/nvram/vm1-restored_VARS.fd")
        self.assertEqual(tree.xpath("devices/interface/link/@state"), ["down", "down"])
        self.assertNotEqual(tree.xpath("string(devices/graphics/@passwd)"), "secret1")
        self.assertEqual(tree.findtext("title"), "web")

    def test_media_are_ejected(self):
        # not in the backup: the restore host may not have them, and the VM would not start
        tree = self.restored()
        self.assertEqual(tree.xpath("devices/disk[@device='cdrom' or @device='floppy']/source"), [])
        self.assertEqual(len(tree.xpath("devices/disk[@device='cdrom' or @device='floppy']")), 3)

    def test_links_kept_when_connected(self):
        self.assertEqual(self.restored(connect=True).xpath("devices/interface/link/@state"), ["up"])


class RestoreOverDefinitionTestCase(unittest.TestCase):
    def test_only_the_disks_sources_change(self):
        from lxml import etree

        from vrtManager.backup import restore_over_definition

        tree = etree.fromstring(restore_over_definition(SOURCE, {"vda": ("/pool/vm1-vda-20261117-1140.qcow2", "qcow2"),
                                                                 "vdb": ("/pool/vm1-vdb-20261117-1140.raw", "raw")}))
        self.assertEqual(tree.xpath("devices/disk[@device='disk']/source/@file"),
                         ["/pool/vm1-vda-20261117-1140.qcow2", "/pool/vm1-vdb-20261117-1140.raw"])
        self.assertEqual(tree.xpath("devices/disk//backingStore"), [])
        source = etree.fromstring(SOURCE)
        for path in ("name", "uuid", "os/nvram", "title"):
            self.assertEqual(tree.findtext(path), source.findtext(path))
        self.assertEqual(tree.xpath("devices/interface/mac/@address"), source.xpath("devices/interface/mac/@address"))
        self.assertEqual(len(tree.xpath("devices/disk[@device='cdrom']/source")), 2)  # the VM's media stay
        # the guest sees it was rolled back: libvirt makes a new generation ID
        self.assertEqual(tree.findtext("genid") or "", "")
        self.assertIsNotNone(tree.find("genid"))


class RestoreHostTestCase(unittest.TestCase):
    def conn(self):
        conn = MagicMock()
        conn.get_networks.return_value = ["default"]
        conn.get_ifaces.return_value = ["br0", "eth0"]
        conn.get_nwfilters.return_value = ["clean-traffic"]
        conn.wvm.getDomainCapabilities.return_value = (
            "<domainCapabilities><os><loader><value>/usr/share/edk2/ovmf/OVMF_CODE.fd</value></loader></os></domainCapabilities>")
        return conn

    def check(self, conn, *texts, definition=SOURCE):
        from vrtManager.backup import check_restore_host

        if not texts:
            check_restore_host(conn, definition)
            return
        with self.assertRaises(util.OperationError) as caught:
            check_restore_host(conn, definition)
        for text in texts:
            self.assertIn(text, str(caught.exception))

    def test_a_host_that_offers_everything(self):
        conn = self.conn()
        self.check(conn)
        conn.wvm.getDomainCapabilities.assert_called_once_with("/usr/libexec/qemu-kvm", "x86_64", "pc-q35-10.1", "kvm", 0)

    def test_a_missing_network_is_refused(self):
        conn = self.conn()
        conn.get_networks.return_value = []
        self.check(conn, "network default")

    def test_a_missing_bridge_is_refused(self):
        conn = self.conn()
        conn.get_ifaces.return_value = ["eth0"]
        self.check(conn, "br0")

    def test_a_missing_filter_is_refused(self):
        conn = self.conn()
        conn.get_nwfilters.return_value = []
        self.check(conn, "clean-traffic")

    def test_an_emulator_or_machine_the_host_lacks_is_refused(self):
        conn = self.conn()
        conn.wvm.getDomainCapabilities.side_effect = error(libvirt.VIR_ERR_INVALID_ARG)
        self.check(conn, "/usr/libexec/qemu-kvm", "pc-q35-10.1")

    def test_a_firmware_the_host_lacks_is_refused(self):
        conn = self.conn()
        conn.wvm.getDomainCapabilities.return_value = "<domainCapabilities><os><loader/></os></domainCapabilities>"
        self.check(conn, "OVMF_CODE.fd")

    def test_a_tpm_needs_the_host_to_offer_its_model_with_swtpm(self):
        conn = self.conn()
        self.check(conn)  # no TPM in the definition
        with_tpm = SOURCE.replace("<devices>", "<devices>" + TPM)
        self.check(conn, "TPM 2.0 tpm-crb", "swtpm", definition=with_tpm)

        def offers(models, backends="<value>emulator</value>", versions="<value>2.0</value>"):
            conn.wvm.getDomainCapabilities.return_value = (
                "<domainCapabilities><os><loader><value>/usr/share/edk2/ovmf/OVMF_CODE.fd</value></loader></os>"
                f"<devices><tpm supported='yes'><enum name='model'>{models}</enum>"
                f"<enum name='backendModel'>{backends}</enum><enum name='backendVersion'>{versions}</enum>"
                "</tpm></devices></domainCapabilities>")

        offers("<value>tpm-tis</value>")
        self.check(conn, "tpm-crb", definition=with_tpm)
        offers("<value>tpm-crb</value>", backends="<value>passthrough</value>")
        self.check(conn, "swtpm", definition=with_tpm)
        offers("<value>tpm-crb</value>", versions="<value>1.2</value>")
        self.check(conn, "swtpm", definition=with_tpm)
        offers("<value>tpm-tis</value><value>tpm-crb</value>")
        self.check(conn, definition=with_tpm)
