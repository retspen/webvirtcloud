"""VM statistics: rates are averages since the sample of the previous answer,
without waiting, when it is from the same run of the VM on the same host and
devices; otherwise over one second. The stats view runs in a sync worker,
polled every 5 s by each open VM page."""

import unittest
from unittest.mock import patch

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from vrtManager.instance import USAGE_MAX_WINDOW, wvmInstance

XML = """<domain><devices>
<disk type='file' device='disk'><source file='/var/lib/libvirt/images/a.qcow2'/><target dev='vda'/></disk>
<disk type='volume' device='disk'><source pool='default' volume='b.qcow2'/><target dev='vdb'/></disk>
<disk type='file' device='cdrom'><target dev='sda'/></disk>
<interface type='hostdev'><mac address='52:54:00:00:00:01'/></interface>
<interface type='network'><mac address='52:54:00:00:00:02'/><target dev='vnet0'/></interface>
</devices></domain>"""


class FakeDomain:
    """Counters grow by a fixed amount per second of the clock."""

    def __init__(self, state, clock):
        self.state = state
        self.clock = clock
        self.domain_id = 7
        self.unsupported = False

    def now(self):
        return self.clock[0]

    def ID(self):
        return self.domain_id

    def info(self):
        return [self.state, 0, 0, 2, int(self.now() * 500_000_000)]  # 0.5 s of CPU time per second

    def blockStats(self, dev):
        n = {"vda": 1, "vdb": 2}[dev]  # disks are read by target name
        written = -1 if self.unsupported and dev == "vdb" else int(self.now() * n * 3000)
        return (0, int(self.now() * n * 1000), 0, written, 0)

    def interfaceStats(self, dev):
        assert dev == "vnet0"
        return (int(self.now() * 100), 0, 0, 0, int(self.now() * 50), 0, 0, 0)


def instance(state, clock):
    proxy = wvmInstance.__new__(wvmInstance)  # no connection: only these calls
    proxy._read_cache = None
    proxy.instance = FakeDomain(state, clock)
    proxy._XMLDesc = lambda flags: XML
    proxy.host_info = ["x86_64", 0, 4]  # 4 host CPUs
    proxy.get_status = lambda: state
    return proxy


class UsageTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        patcher = patch("vrtManager.instance.time")
        self.addCleanup(patcher.stop)
        self.time = patcher.start()
        self.time.monotonic.side_effect = lambda: self.clock[0]
        self.time.sleep.side_effect = self.advance

    def advance(self, seconds):
        self.clock[0] += seconds

    def usage(self, proxy, previous=None):
        result = proxy.usage(previous)
        self.time.sleep.reset_mock()
        return result

    def test_without_a_sample_over_one_second(self):
        proxy = instance(1, self.clock)
        result = proxy.usage()
        self.time.sleep.assert_called_once_with(1)
        self.assertEqual((result["cpu"], result["window"]), (12.5, 1.0))  # 0.5 s of 4 host CPUs
        # a pool volume is measured like a file
        self.assertEqual(
            result["disks"], [{"dev": "vda", "rd": 1000, "wr": 3000}, {"dev": "vdb", "rd": 2000, "wr": 6000}]
        )
        # bits; the NIC without a target is not measured
        self.assertEqual(result["nics"], [{"mac": "52:54:00:00:00:01", "rx": None, "tx": None}, {"mac": "52:54:00:00:00:02", "rx": 800, "tx": 400}])
        self.assertEqual(result["sample"]["counters"][3], 101.0)

    def test_since_the_previous_sample_without_waiting(self):
        proxy = instance(1, self.clock)
        sample = self.usage(proxy)["sample"]
        self.advance(9.5)
        result = proxy.usage(sample)
        self.time.sleep.assert_not_called()
        self.assertEqual((result["cpu"], result["window"]), (12.5, 9.5))
        self.assertEqual(result["disks"][1], {"dev": "vdb", "rd": 2000, "wr": 6000})  # per second
        self.assertEqual(result["nics"][1], {"mac": "52:54:00:00:00:02", "rx": 800, "tx": 400})
        self.assertEqual(result["sample"]["counters"][3], 110.5)

    def test_a_sample_of_another_run_host_or_devices_is_not_used(self):
        def restarted(proxy):
            proxy.instance.domain_id = 8

        def other_host_cpus(proxy):
            proxy.host_info = ["x86_64", 0, 8]

        def nic_renamed(proxy):
            proxy._XMLDesc = lambda flags: XML.replace("vnet0", "vnet1")

        for change in (restarted, other_host_cpus, nic_renamed):
            with self.subTest(change.__name__):
                proxy = instance(1, self.clock)
                sample = self.usage(proxy)["sample"]
                change(proxy)
                self.advance(5)
                proxy.instance.interfaceStats = lambda dev: (0,) * 8
                self.assertEqual(proxy.usage(sample)["window"], 1.0)
                self.time.sleep.assert_called_once_with(1)
                self.time.sleep.reset_mock()

    def test_a_sample_too_old_from_the_future_or_counting_back_is_not_used(self):
        for name, seconds in (("too old", USAGE_MAX_WINDOW + 1), ("future", -5), ("same time", 0)):
            with self.subTest(name):
                proxy = instance(1, self.clock)
                sample = self.usage(proxy)["sample"]
                self.advance(seconds)
                self.assertEqual(proxy.usage(sample)["window"], 1.0)
                self.time.sleep.assert_called_once_with(1)
                self.time.sleep.reset_mock()
        proxy = instance(1, self.clock)
        sample = self.usage(proxy)["sample"]
        sample["counters"][0] += 10**12  # CPU time went back: a restart with the same domain ID
        self.advance(5)
        self.assertEqual(proxy.usage(sample)["cpu"], 12.5)
        self.time.sleep.assert_called_once_with(1)

    def test_a_counter_the_host_does_not_report_has_no_value(self):
        proxy = instance(1, self.clock)
        proxy.instance.unsupported = True
        disks = proxy.usage()["disks"]
        self.assertEqual(disks[1], {"dev": "vdb", "rd": 2000, "wr": None})

    def test_a_vm_restarted_during_the_second_has_no_values(self):
        proxy = instance(1, self.clock)
        domain = proxy.instance
        real_sleep = self.time.sleep.side_effect

        def restart(seconds):
            real_sleep(seconds)
            domain.info = lambda: [1, 0, 0, 2, 0]  # CPU time starts over

        self.time.sleep.side_effect = restart
        result = proxy.usage()
        self.assertEqual((result["cpu"], result["window"]), (None, None))
        self.assertEqual(result["disks"][0], {"dev": "vda", "rd": None, "wr": None})
        self.assertIn("sample", result)

    def test_a_paused_or_shut_off_vm_is_not_sampled(self):
        for state in (3, 5):
            with self.subTest(state=state):
                result = instance(state, self.clock).usage()
                self.time.sleep.assert_not_called()
                self.assertEqual(
                    result,
                    {
                        "cpu": 0,
                        "disks": [{"dev": "vda", "rd": 0, "wr": 0}, {"dev": "vdb", "rd": 0, "wr": 0}],
                        "nics": [{"mac": "52:54:00:00:00:01", "rx": 0, "tx": 0}, {"mac": "52:54:00:00:00:02", "rx": 0, "tx": 0}],
                    },
                )


if __name__ == "__main__":
    unittest.main()
