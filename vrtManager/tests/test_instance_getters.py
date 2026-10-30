"""The VM page's device getters read each device on its own: a value of one
NIC, CD-ROM or boot device does not carry over to the next."""

import unittest
from unittest.mock import MagicMock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from libvirt import libvirtError
from vrtManager.instance import wvmInstance

XML = """<domain>
  <os><type arch='x86_64'>hvm</type></os>
  <devices>
    <disk type='file' device='disk'><source file='/pool/a.qcow2'/><target dev='vda' bus='virtio'/><boot order='3'/></disk>
    <disk type='block' device='disk'><source dev='/dev/vg/b'/><target dev='vdb' bus='virtio'/><boot order='4'/></disk>
    <disk type='file' device='cdrom'><source file='/iso/x.iso'/><target dev='sda' bus='sata'/></disk>
    <disk type='file' device='cdrom'><target dev='sdb' bus='sata'/></disk>
    <interface type='network'>
      <mac address='52:54:10:00:00:01'/><source network='default'/><model type='virtio'/>
      <bandwidth><inbound average='100' peak='200' burst='300'/><outbound average='10' peak='20' burst='30'/></bandwidth>
    </interface>
    <interface type='bridge'><mac address='52:54:10:00:00:02'/><source bridge='br0'/><boot order='1'/></interface>
    <interface type='direct'><mac address='52:54:10:00:00:03'/><boot order='2'/></interface>
  </devices>
</domain>"""


def proxy():
    p = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    p._ip_cache = {"qemuga": {}, "arp": {}}
    p._XMLDesc = lambda flags: XML
    volumes = {"/iso/x.iso": ("x.iso", "iso")}

    def volume(path):
        if path not in volumes:
            raise libvirtError("no volume")
        name, pool = volumes[path]
        return MagicMock(**{"name.return_value": name, "info.return_value": [0, 10, 4],
                            "storagePoolLookupByVolume.return_value.name.return_value": pool})

    p.get_volume_by_path = volume
    return p


class DeviceGettersTestCase(unittest.TestCase):
    def test_a_nic_without_qos_source_or_model_has_none(self):
        nics = proxy().get_net_devices()
        self.assertEqual(nics[0]["inbound"], {"average": "100", "peak": "200", "burst": "300"})
        self.assertEqual(nics[0]["outbound"], {"average": "10", "peak": "20", "burst": "30"})
        self.assertEqual([(n["inbound"], n["outbound"]) for n in nics[1:]], [([], [])] * 2)
        self.assertEqual([(n["nic"], n["model"]) for n in nics], [("default", "virtio"), ("br0", ""), ("", "")])

    def test_an_empty_cdrom_shows_no_pool(self):
        media = proxy().get_media_devices()
        self.assertEqual(
            media,
            [
                {"dev": "sda", "image": "x.iso", "storage": "iso", "path": "/iso/x.iso", "bus": "sata"},
                {"dev": "sdb", "image": None, "storage": None, "path": None, "bus": "sata"},
            ],
        )

    def test_every_boot_device_has_its_target(self):
        order = proxy().get_bootorder()
        self.assertEqual(
            [order[i]["target"] for i in range(4)],
            ["52:54:10:00:00:02", "52:54:10:00:00:03", "vda", "vdb"],
        )


class RefreshInstancePoolsTestCase(unittest.TestCase):
    def test_only_pools_holding_a_disk_are_refreshed(self):
        p = proxy()
        p.get_disk_devices = lambda: [{"path": "/pool/a.qcow2"}, {"path": "/elsewhere/b.img"}, {"path": None}]
        pool = MagicMock()
        p.get_wvmStorages = lambda: MagicMock(get_pool_by_target=lambda target: pool if target == "/pool" else None)
        p.refresh_instance_pools()
        pool.refresh.assert_called_once_with(0)
