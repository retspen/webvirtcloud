"""wvmInstance.cached_reads(): inside the block the domain XML (per flags),
the VM's state and each disk's volume are read from libvirt once; outside it
every read goes to libvirt, as code that changes the VM needs. The host's
info and capabilities are read once per object."""

import unittest
from unittest.mock import MagicMock

from libvirt import libvirtError
from vrtManager.instance import wvmInstance


class FakeDomain:
    def __init__(self):
        self.reads = []
        self.fail = False

    def info(self):
        self.reads.append("info")
        return [1, 0, 0, 0, 0]

    def XMLDesc(self, flags):
        if self.fail:
            raise RuntimeError("libvirt error")
        self.reads.append(flags)
        return f"<domain flags='{flags}' read='{len(self.reads)}'/>"

    def blockInfo(self, dev):  # a disk no pool holds that libvirt cannot read either
        raise libvirtError("cannot read")


class FakeConn:
    def __init__(self):
        self.caps = 0
        self.defined = []

    def getInfo(self):
        self.caps += 1
        return ["x86_64", 2048, 4, 0, 1, 2, 2, 1]

    def getCapabilities(self):
        self.caps += 1
        return "<capabilities/>"

    def defineXML(self, xml):
        self.defined.append(xml)


def proxy():
    p = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    p.instance = FakeDomain()
    p.wvm = FakeConn()
    return p


class CachedReadsTestCase(unittest.TestCase):
    def test_outside_the_block_every_read_goes_to_libvirt(self):
        p = proxy()
        p._XMLDesc(0)
        p._XMLDesc(0)
        p.get_status()
        p.get_status()
        self.assertEqual(p.instance.reads, [0, 0, "info", "info"])

    def test_inside_the_block_each_flags_value_is_read_once(self):
        p = proxy()
        with p.cached_reads():
            first = [p._XMLDesc(0), p._XMLDesc(1), p._XMLDesc(3)]
            again = [p._XMLDesc(0), p._XMLDesc(1), p._XMLDesc(3)]
        self.assertEqual(first, again)
        self.assertEqual(p.instance.reads, [0, 1, 3])

    def test_the_block_ends_with_its_cache(self):
        p = proxy()
        with p.cached_reads():
            p._XMLDesc(0)
        with p.cached_reads():
            p._XMLDesc(0)
        p._XMLDesc(0)
        self.assertEqual(p.instance.reads, [0, 0, 0])

    def test_an_error_inside_the_block_still_ends_it(self):
        p = proxy()
        with self.assertRaises(ValueError), p.cached_reads():
            p._XMLDesc(0)
            raise ValueError
        p._XMLDesc(0)
        self.assertEqual(p.instance.reads, [0, 0])

    def test_a_failed_read_is_not_cached(self):
        p = proxy()
        with p.cached_reads():
            p.instance.fail = True
            with self.assertRaises(RuntimeError):
                p._XMLDesc(0)
            p.instance.fail = False
            p._XMLDesc(0)
        self.assertEqual(p.instance.reads, [0])

    def test_a_definition_change_drops_the_cache(self):
        p = proxy()
        with p.cached_reads():
            p._XMLDesc(3)
            p._defineXML("<domain/>")
            p._XMLDesc(3)
        self.assertEqual(p.instance.reads, [3, 3])

    def test_blocks_do_not_nest(self):
        p = proxy()
        with p.cached_reads(), self.assertRaises(RuntimeError), p.cached_reads():
            pass

    def test_two_proxies_do_not_share_a_cache(self):
        a, b = proxy(), proxy()
        with a.cached_reads():
            a._XMLDesc(0)
            b._XMLDesc(0)
            b._XMLDesc(0)
        self.assertEqual((a.instance.reads, b.instance.reads), ([0], [0, 0]))

    def test_the_state_and_host_info_are_read_once(self):
        p = proxy()
        with p.cached_reads():
            for _ in range(2):
                p.get_status()
                p.get_max_memory()
                p.get_max_cpus()
        self.assertEqual((p.instance.reads, p.wvm.caps), (["info"], 1))
        p.get_status()
        self.assertEqual(p.instance.reads, ["info", "info"])

def volume_proxy(paths):
    """A proxy whose host has volumes at paths (pool "pool", size 10, used 4)."""
    p = proxy()
    p.lookups = []

    def lookup(path):
        p.lookups.append(path)
        if path not in paths:
            raise libvirtError("no storage vol with matching path")
        vol = MagicMock()
        vol.name.return_value = path.rsplit("/", 1)[-1]
        vol.info.return_value = [0, 10, 4]
        vol.storagePoolLookupByVolume.return_value.name.return_value = "pool"
        return vol

    p.get_volume_by_path = lookup
    return p


class VolumeDetailsTestCase(unittest.TestCase):
    def test_inside_the_block_each_path_is_looked_up_once(self):
        p = volume_proxy({"/p/a.qcow2", "/p/b.raw"})
        with p.cached_reads():
            for _ in range(2):
                self.assertEqual(p._volume_details("/p/a.qcow2"), ("a.qcow2", 10, 4, "pool"))
                p._volume_details("/p/b.raw")
                self.assertIsNone(p._volume_details("/dev/sdx"))
        self.assertEqual(p.lookups, ["/p/a.qcow2", "/p/b.raw", "/dev/sdx"])

    def test_outside_the_block_and_after_a_change_the_volume_is_read_again(self):
        p = volume_proxy({"/p/a.qcow2"})
        p._volume_details("/p/a.qcow2")
        with p.cached_reads():
            p._volume_details("/p/a.qcow2")
            p._defineXML("<domain/>")
            p._volume_details("/p/a.qcow2")
        p._volume_details("/p/a.qcow2")
        self.assertEqual(len(p.lookups), 4)


def disk(path, cache):
    return (
        f"<disk type='file' device='disk'><driver name='qemu' type='qcow2' cache='{cache}'/>"
        f"<source file='{path}'/><target dev='vda' bus='virtio'/></disk>"
    )


class DiskListsTestCase(unittest.TestCase):
    """The page lists the running and the persistent disks; both share a
    path's volume, each keeps its own settings."""

    def lists(self, live, config, volumes):
        p = volume_proxy(volumes)
        xml = {0: f"<domain><devices>{live}</devices></domain>", 3: f"<domain><devices>{config}</devices></domain>"}
        p.instance.XMLDesc = lambda flags: xml[flags]
        with p.cached_reads():
            return p, p.get_disk_devices(), p.get_disk_devices(config=True)

    def test_one_path_in_both_lists_is_looked_up_once(self):
        p, live, config = self.lists(disk("/p/a.qcow2", "none"), disk("/p/a.qcow2", "writeback"), {"/p/a.qcow2"})
        self.assertEqual(p.lookups, ["/p/a.qcow2"])
        self.assertEqual([(d["image"], d["storage"], d["size"], d["cache"]) for d in live], [("a.qcow2", "pool", 10, "none")])
        self.assertEqual([d["cache"] for d in config], ["writeback"])
        self.assertIsNot(live[0], config[0])

    def test_a_pending_disk_change_is_looked_up_on_its_own(self):
        p, live, config = self.lists(disk("/p/a.qcow2", "none"), disk("/p/b.qcow2", "none"), {"/p/a.qcow2", "/p/b.qcow2"})
        self.assertEqual(p.lookups, ["/p/a.qcow2", "/p/b.qcow2"])
        self.assertEqual((live[0]["image"], config[0]["image"]), ("a.qcow2", "b.qcow2"))

    def test_a_disk_outside_any_pool_shows_its_path(self):
        p, live, _ = self.lists(disk("/srv/x.img", "none"), disk("/srv/x.img", "none"), set())
        self.assertEqual(p.lookups, ["/srv/x.img"])
        self.assertEqual((live[0]["image"], live[0]["storage"], live[0]["size"]), ("/srv/x.img", None, None))
