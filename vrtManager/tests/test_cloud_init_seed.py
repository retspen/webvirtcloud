"""A new VM's cloud-init NoCloud seed: an ISO labelled cidata with its
meta-data and user-data, written into a storage pool as a volume."""

import io
import json
import unittest
from unittest.mock import MagicMock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

import pycdlib
from libvirt import VIR_ERR_NO_STORAGE_VOL, libvirtError
from vrtManager.connection import wvmConnect
from vrtManager.create import nocloud_seed, wvmCreate

UUID = "11111111-2222-3333-4444-555555555555"
USER_DATA = "#cloud-config\nssh_authorized_keys:\n  - ssh-ed25519 AAAA laptop\n"


def read_iso(data):
    iso = pycdlib.PyCdlib()
    iso.open_fp(io.BytesIO(data))
    files = {}
    for name in ("meta-data", "user-data"):
        out = io.BytesIO()
        iso.get_file_from_iso_fp(out, rr_path=f"/{name}")
        files[name] = out.getvalue().decode()
        out = io.BytesIO()
        iso.get_file_from_iso_fp(out, joliet_path=f"/{name}")
        assert out.getvalue().decode() == files[name]
    label = iso.pvd.volume_identifier.decode().strip()
    iso.close()
    return label, files


class SeedTestCase(unittest.TestCase):
    def test_the_seed_carries_the_vms_identity_and_user_data(self):
        label, files = read_iso(nocloud_seed(UUID, "web-1", USER_DATA))
        # cloud-init finds the seed by its label, and runs again only for a new instance-id
        self.assertEqual(label, "cidata")
        self.assertEqual(json.loads(files["meta-data"]), {"instance-id": UUID, "local-hostname": "web-1"})
        self.assertEqual(files["user-data"], USER_DATA)

    def test_any_vm_name_stays_a_string_hostname(self):
        # YAML would read 123 as a number, yes as true and null as nothing
        import yaml

        for name in ("123", "yes", "null", "1e3", "web.example"):
            with self.subTest(name=name):
                meta = yaml.safe_load(read_iso(nocloud_seed(UUID, name, USER_DATA))[1]["meta-data"])
                self.assertEqual(meta, {"instance-id": UUID, "local-hostname": name})

    def test_the_seed_goes_into_the_pool_as_a_volume(self):
        conn = wvmCreate.__new__(wvmCreate)
        conn.wvm = MagicMock()
        pool = conn.wvm.storagePoolLookupByName.return_value
        pool.createXML.return_value.path.return_value = f"/var/lib/libvirt/images/cidata-{UUID}.iso"
        sent = []
        conn.wvm.newStream.return_value.sendAll.side_effect = lambda handler, buffer: sent.append(buffer.read())
        path = conn.create_seed("default", UUID, "web-1", USER_DATA)
        self.assertEqual(path, f"/var/lib/libvirt/images/cidata-{UUID}.iso")
        conn.wvm.storagePoolLookupByName.assert_called_once_with("default")
        xml = pool.createXML.call_args.args[0]
        self.assertIn(f"<name>cidata-{UUID}.iso</name>", xml)
        self.assertEqual(json.loads(read_iso(sent[0])[1]["meta-data"])["instance-id"], UUID)
        self.assertIn(f"<capacity>{len(sent[0])}</capacity>", xml)


class UploadVolumeTestCase(unittest.TestCase):
    def test_a_failed_write_leaves_no_volume(self):
        conn = wvmConnect.__new__(wvmConnect)
        conn.wvm = MagicMock()
        conn.wvm.newStream.return_value.finish.side_effect = RuntimeError("stream broke")
        pool = MagicMock()
        with self.assertRaises(RuntimeError):
            conn.upload_volume(pool, "a.iso", b"data")
        pool.createXML.return_value.delete.assert_called_once_with(0)


class DeleteWithDisksTestCase(unittest.TestCase):
    def vm(self, seed_in_pool=True):
        from vrtManager.instance import wvmInstance

        vm = wvmInstance.__new__(wvmInstance)
        vm.wvm = MagicMock()
        vm.refresh_instance_pools = MagicMock()
        vm.get_uuid = lambda: UUID
        vm.get_disk_devices = lambda: [{"path": "/pool/web-1.qcow2"}]
        vm._snapshot_chain_files = lambda own: []
        vm.paths_used_by_other_domains = lambda own: set()
        vm.backing_path = lambda path: None
        pool = MagicMock()
        if seed_in_pool:
            pool.storageVolLookupByName.return_value.path.return_value = f"/pool/cidata-{UUID}.iso"
        else:
            missing = libvirtError("no volume")
            missing.get_error_code = lambda: VIR_ERR_NO_STORAGE_VOL
            pool.storageVolLookupByName.side_effect = missing
        vm.wvm.listAllStoragePools.return_value = [pool]
        return vm, pool

    def test_the_vms_own_seed_goes_with_its_disks_even_when_ejected(self):
        # found in the pools by its name, not in a CD-ROM drive: one may hold an installer now
        vm, pool = self.vm()
        self.assertEqual(vm.split_disk_paths_by_use(), (["/pool/web-1.qcow2", f"/pool/cidata-{UUID}.iso"], []))
        pool.storageVolLookupByName.assert_called_once_with(f"cidata-{UUID}.iso")

    def test_a_vm_without_a_seed_deletes_only_its_disks(self):
        vm, _ = self.vm(seed_in_pool=False)
        self.assertEqual(vm.split_disk_paths_by_use(), (["/pool/web-1.qcow2"], []))


class CloneTestCase(unittest.TestCase):
    def test_a_clone_does_not_take_the_vms_seed(self):
        # the seed holds the VM's instance-id and hostname: the clone's CD-ROM is left empty
        from vrtManager.instance import wvmInstance

        vm = wvmInstance.__new__(wvmInstance)
        vm.get_instances = lambda: []
        vm.get_uuid = lambda: UUID
        vm._XMLDesc = lambda flags: (
            "<domain><name>web-1</name><uuid>" + UUID + "</uuid><devices>"
            "<disk type='file' device='cdrom'><source file='/pool/cidata-" + UUID + ".iso'/><target dev='sda'/></disk>"
            "<disk type='file' device='cdrom'><source file='/iso/alma10.iso'/><target dev='sdb'/></disk>"
            "</devices></domain>")
        tree, _ = vm._clone_definition({"name": "web-2"}, "99999999-2222-3333-4444-555555555555")
        sources = [d.find("source").get("file") if d.find("source") is not None else None
                   for d in tree.findall("devices/disk")]
        self.assertEqual(sources, [None, "/iso/alma10.iso"])
