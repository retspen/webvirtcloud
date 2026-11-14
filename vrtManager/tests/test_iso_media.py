import unittest
from unittest.mock import MagicMock

from libvirt import (
    VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE,
    VIR_DOMAIN_AFFECT_CONFIG,
    VIR_DOMAIN_AFFECT_LIVE,
    libvirtError,
)
from lxml import etree
from vrtManager.instance import wvmInstance

DOMAIN = """<domain><devices>
<disk type='file' device='cdrom'><driver name='qemu' type='raw'/><target dev='sda' bus='sata'/></disk>
<disk type='file' device='cdrom'><driver name='qemu' type='raw'/><target dev='sdb' bus='sata'/></disk>
</devices></domain>"""


def vm(active):
    inst = wvmInstance.__new__(wvmInstance)
    inst.instance = MagicMock()
    inst.instance.isActive.return_value = active
    inst._XMLDesc = MagicMock(return_value=DOMAIN)
    return inst


class IsoMediaTestCase(unittest.TestCase):
    """Media change goes through updateDeviceFlags for the right CD-ROM."""

    def updates(self, inst):
        return [
            (etree.fromstring(c.args[0]).find("target").get("dev"), etree.fromstring(c.args[0]).xpath("string(source/@file)"), c.args[1])
            for c in inst.instance.updateDeviceFlags.call_args_list
        ]

    def test_stopped_vm_changes_only_the_persistent_definition(self):
        inst = vm(active=False)
        inst._set_cdrom_media("sdb", "/iso/a.iso")
        self.assertEqual(self.updates(inst), [("sdb", "/iso/a.iso", VIR_DOMAIN_AFFECT_CONFIG)])

    def test_running_vm_changes_live_then_persistent(self):
        inst = vm(active=True)
        inst._set_cdrom_media("sdb", None)
        self.assertEqual(
            self.updates(inst), [("sdb", "", VIR_DOMAIN_AFFECT_LIVE), ("sdb", "", VIR_DOMAIN_AFFECT_CONFIG)]
        )

    def test_an_iso_in_a_host_drive_makes_it_a_file_drive(self):
        inst = vm(active=False)
        inst._XMLDesc = MagicMock(return_value=DOMAIN.replace("<disk type='file'", "<disk type='block'"))
        inst._set_cdrom_media("sdb", "/iso/a.iso")
        disk = etree.fromstring(inst.instance.updateDeviceFlags.call_args.args[0])
        self.assertEqual((disk.get("type"), disk.find("source").get("file")), ("file", "/iso/a.iso"))

    def test_unknown_cdrom_changes_nothing(self):
        inst = vm(active=True)
        with self.assertRaises(libvirtError):
            inst._set_cdrom_media("sdz", "/iso/a.iso")
        inst.instance.updateDeviceFlags.assert_not_called()


def pool(volumes, refresh_error=False, list_error=False):
    p = MagicMock()
    if refresh_error:
        p.refresh.side_effect = libvirtError("refresh failed")
    if list_error:
        p.listVolumes.side_effect = libvirtError("pool is not active")
    else:
        p.listVolumes.return_value = volumes
    return p


class IsoListTestCase(unittest.TestCase):
    """The CD-ROM choices are the .iso volumes libvirt knows in the active
    pools; the pools are read again only when asked."""

    def wvm(self, *pools):
        inst = wvmInstance.__new__(wvmInstance)
        inst.wvm = MagicMock()
        inst.wvm.listAllStoragePools.return_value = list(pools)
        return inst

    def test_iso_volumes_of_the_active_pools_without_a_refresh(self):
        a, b = pool(["a.iso", "disk.qcow2"]), pool(["B.ISO"])
        inst = self.wvm(a, b)
        self.assertEqual(inst.get_iso_media(), ["a.iso", "B.ISO"])
        inst.wvm.listAllStoragePools.assert_called_once_with(VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE)
        a.refresh.assert_not_called()
        b.refresh.assert_not_called()

    def test_a_pool_stopped_meanwhile_is_skipped(self):
        inst = self.wvm(pool([], list_error=True), pool(["b.iso"]))
        self.assertEqual(inst.get_iso_media(), ["b.iso"])

    def test_refresh_reads_every_active_pool_again(self):
        a, b = pool([]), pool([])
        inst = self.wvm(a, b)
        self.assertEqual(inst.refresh_iso_pools(), {})
        inst.wvm.listAllStoragePools.assert_called_once_with(VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE)
        a.refresh.assert_called_once_with(0)
        b.refresh.assert_called_once_with(0)

    def test_a_failed_refresh_is_returned_and_the_others_still_run(self):
        a, b = pool([], refresh_error=True), pool([])
        a.name.return_value = "busy"
        failed = self.wvm(a, b).refresh_iso_pools()
        self.assertEqual(list(failed), ["busy"])
        self.assertIsInstance(failed["busy"], libvirtError)
        b.refresh.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
