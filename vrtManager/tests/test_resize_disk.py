import unittest
from unittest.mock import MagicMock

from libvirt import VIR_DOMAIN_BLOCK_RESIZE_BYTES, VIR_STORAGE_VOL_BLOCK, VIR_STORAGE_VOL_FILE
from vrtManager.instance import wvmInstance

SIZE = 10 << 30


def vm(active, vol_type):
    inst = wvmInstance.__new__(wvmInstance)
    inst.instance = MagicMock()
    inst.instance.isActive.return_value = active
    vol = MagicMock()
    vol.info.return_value = [vol_type, 0, 0]
    inst.get_volume_by_path = MagicMock(return_value=vol)
    inst.resize_disk([{"path": "/dev/vg/disk", "size_new": SIZE}])
    return inst, vol


class ResizeDiskTestCase(unittest.TestCase):
    def test_running_block_volume_grows_in_the_pool_then_in_qemu(self):
        inst, vol = vm(active=True, vol_type=VIR_STORAGE_VOL_BLOCK)
        vol.resize.assert_called_once_with(SIZE)
        inst.instance.blockResize.assert_called_once_with("/dev/vg/disk", SIZE, VIR_DOMAIN_BLOCK_RESIZE_BYTES)

    def test_running_image_file_grows_through_qemu_only(self):
        # qemu-img cannot take the image lock QEMU holds
        inst, vol = vm(active=True, vol_type=VIR_STORAGE_VOL_FILE)
        vol.resize.assert_not_called()
        inst.instance.blockResize.assert_called_once()

    def test_stopped_vm_grows_the_volume(self):
        inst, vol = vm(active=False, vol_type=VIR_STORAGE_VOL_FILE)
        vol.resize.assert_called_once_with(SIZE)
        inst.instance.blockResize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
