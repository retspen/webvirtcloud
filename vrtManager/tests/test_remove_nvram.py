"""After a migration took a VM away, its NVRAM file is removed from the
source when it is in libvirt's per-host NVRAM directory and the destination
does not share that directory; a VM later created on the source with the same
name would otherwise start with the old UEFI variables."""

from unittest import TestCase
from unittest.mock import MagicMock

import libvirt

from vrtManager.connection import NVRAM_DIR, wvmConnect

PATH = NVRAM_DIR + "/vm_VARS.fd"


def error(code):
    err = libvirt.libvirtError("error %d" % code)
    err.err = (code, libvirt.VIR_FROM_STORAGE, str(err), 2, None, None, None, 0, 0)
    return err


def pool(path, volumes=(), create_error=None):
    p = MagicMock()
    p.XMLDesc.return_value = f"<pool type='dir'><name>p</name><target><path>{path}</path></target></pool>"
    p.vols = {name: MagicMock() for name in volumes}
    p.created = []

    def lookup(name):
        if name not in p.vols:
            raise error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        return p.vols[name]

    def create(xml, flags):
        if create_error is not None:
            raise create_error
        vol = MagicMock()
        p.created.append(vol)
        return vol

    p.storageVolLookupByName.side_effect = lookup
    p.createXML.side_effect = create
    return p


def connect(pools=(), transient=None):
    conn = wvmConnect.__new__(wvmConnect)
    conn.wvm = MagicMock()
    conn.wvm.listAllStoragePools.return_value = list(pools)
    conn.wvm.storagePoolCreateXML.return_value = transient
    return conn


def local_destination():
    return connect([pool(NVRAM_DIR)])


class RemoveNvramTestCase(TestCase):
    def test_a_file_outside_the_nvram_directory_is_kept(self):
        conn = connect()
        for path in ("/srv/shared/nvram/vm_VARS.fd", NVRAM_DIR + "/sub/vm_VARS.fd", "relative_VARS.fd"):
            with self.subTest(path=path):
                self.assertFalse(conn.remove_nvram(path, local_destination()))
        self.assertFalse(conn.wvm.method_calls)

    def test_a_pool_on_the_directory_is_used(self):
        existing = pool(NVRAM_DIR + "/", ["vm_VARS.fd"])
        conn = connect([pool("/var/lib/libvirt/images"), existing])
        self.assertTrue(conn.remove_nvram(PATH, local_destination()))
        existing.vols["vm_VARS.fd"].delete.assert_called_once_with(0)
        self.assertFalse(conn.wvm.storagePoolCreateXML.called)
        self.assertFalse(existing.destroy.called)

    def test_pools_without_a_target_path_are_skipped(self):
        rbd = MagicMock()
        rbd.XMLDesc.return_value = "<pool type='rbd'><name>ceph</name><source><name>rbd</name></source></pool>"
        transient = pool(NVRAM_DIR, ["vm_VARS.fd"])
        conn = connect([rbd], transient)
        self.assertTrue(conn.remove_nvram(PATH, local_destination()))
        transient.vols["vm_VARS.fd"].delete.assert_called_once_with(0)

    def test_without_a_pool_a_transient_one_is_used_and_stopped(self):
        transient = pool(NVRAM_DIR, ["vm_VARS.fd"])
        conn = connect([pool("/var/lib/libvirt/images")], transient)
        self.assertTrue(conn.remove_nvram(PATH, local_destination()))
        self.assertIn(f"<path>{NVRAM_DIR}</path>", conn.wvm.storagePoolCreateXML.call_args[0][0])
        transient.vols["vm_VARS.fd"].delete.assert_called_once_with(0)
        transient.destroy.assert_called_once_with()

    def test_a_directory_the_destination_shares_is_left_alone(self):
        # the destination cannot create the marker the source just created
        source = pool(NVRAM_DIR, ["vm_VARS.fd"])
        destination = connect([pool(NVRAM_DIR, create_error=error(libvirt.VIR_ERR_STORAGE_VOL_EXIST))])
        self.assertFalse(connect([source]).remove_nvram(PATH, destination))
        self.assertFalse(source.vols["vm_VARS.fd"].delete.called)
        source.created[0].delete.assert_called_once_with(0)  # the marker is gone

    def test_a_directory_whose_sharing_cannot_be_told_is_left_alone(self):
        source = pool(NVRAM_DIR, ["vm_VARS.fd"])
        destination = connect([pool(NVRAM_DIR, create_error=error(libvirt.VIR_ERR_SYSTEM_ERROR))])
        self.assertFalse(connect([source]).remove_nvram(PATH, destination))
        self.assertFalse(source.vols["vm_VARS.fd"].delete.called)

    def test_both_markers_are_removed(self):
        source = pool(NVRAM_DIR, ["vm_VARS.fd"])
        other = pool(NVRAM_DIR)
        self.assertTrue(connect([source]).remove_nvram(PATH, connect([other])))
        self.assertEqual(source.createXML.call_args, other.createXML.call_args)  # one name
        source.created[0].delete.assert_called_once_with(0)
        other.created[0].delete.assert_called_once_with(0)

    def test_when_the_destination_cannot_be_checked_nothing_is_deleted(self):
        source = pool(NVRAM_DIR, ["vm_VARS.fd"])
        destination = connect([], None)
        destination.wvm.storagePoolCreateXML.side_effect = error(libvirt.VIR_ERR_INTERNAL_ERROR)
        with self.assertRaises(libvirt.libvirtError):
            connect([source]).remove_nvram(PATH, destination)
        self.assertFalse(source.vols["vm_VARS.fd"].delete.called)
        self.assertEqual(source.created, [])  # both pools are opened before the check

    def test_the_transient_pool_is_stopped_when_the_delete_fails(self):
        transient = pool(NVRAM_DIR, ["vm_VARS.fd"])
        transient.vols["vm_VARS.fd"].delete.side_effect = error(libvirt.VIR_ERR_INTERNAL_ERROR)
        conn = connect([], transient)
        with self.assertRaises(libvirt.libvirtError):
            conn.remove_nvram(PATH, local_destination())
        transient.destroy.assert_called_once_with()

    def test_a_missing_file_is_nothing_to_remove(self):
        transient = pool(NVRAM_DIR)
        conn = connect([], transient)
        self.assertFalse(conn.remove_nvram(PATH, local_destination()))
        transient.destroy.assert_called_once_with()
