"""A wvmConnect reads the host's info and capabilities once, and its domain
capabilities once per emulator, arch, machine and domain type: the create
page's getters parse the capabilities some 60 times, the overview reads the
info four times. An object lives for one request. The interfaces page lists
only the host's network devices, not all of them, and knows whether the host
can change interfaces at all."""

import unittest
from unittest.mock import MagicMock

from django.conf import settings

if not settings.configured:
    settings.configure(MAC_OUI="52:54:10")

from libvirt import (
    VIR_CONNECT_LIST_NODE_DEVICES_CAP_NET,
    VIR_DOMAIN_PAUSED,
    VIR_DOMAIN_RUNNING,
    VIR_DOMAIN_SHUTOFF,
    VIR_ERR_NO_SUPPORT,
    VIR_ERR_OPERATION_DENIED,
    VIR_ERR_XML_ERROR,
    libvirtError,
)
from vrtManager.connection import wvmConnect
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.storage import wvmStorages

CAPABILITIES = """<capabilities><host><cpu><arch>x86_64</arch></cpu></host>
<guest><os_type>hvm</os_type><arch name='x86_64'><emulator>/usr/bin/qemu-kvm</emulator>
<machine>pc-q35-9.0</machine><machine canonical='pc-q35-9.0'>q35</machine><machine canonical='pc-i440fx-9.0'>pc</machine>
<domain type='qemu'/><domain type='kvm'/></arch></guest></capabilities>"""


class FakeConn:
    def __init__(self):
        self.reads = []

    def getCapabilities(self):
        self.reads.append("capabilities")
        return CAPABILITIES

    def getInfo(self):
        self.reads.append("info")
        return ["x86_64", 2048, 4, 0, 1, 2, 2, 1]

    def getMemoryStats(self, cell, flags):
        self.reads.append("memory")
        return {"buffers": 0, "free": 1048576, "cached": 0}

    def getHostname(self):
        return "host"

    def getSysinfo(self, flags):
        return "<sysinfo/>"

    def getURI(self):
        return "qemu:///system"

    def getDomainCapabilities(self, emulator, arch, machine, virttype):
        self.reads.append((emulator, arch, machine, virttype))
        return "<domainCapabilities/>"


def connection(cls=wvmConnect):
    conn = cls.__new__(cls)  # no libvirt connection: only these calls
    conn.wvm = FakeConn()
    return conn


class CapabilitiesOnceTestCase(unittest.TestCase):
    def test_the_capabilities_are_read_once_for_all_getters(self):
        conn = connection()
        for _ in range(2):
            conn.get_emulator("x86_64")
            conn.get_machine_types("x86_64")
            conn.get_hypervisors_domain_types()
            conn.get_cap_xml()
        self.assertEqual(conn.wvm.reads, ["capabilities"])

    def test_domain_capabilities_are_read_once_per_machine(self):
        conn = connection()
        for _ in range(2):
            conn.get_dom_cap_xml("x86_64", "q35")
            conn.get_dom_cap_xml("x86_64", "pc")
            conn.get_dom_cap_xml("x86_64", "unknown")  # falls back to pc
        self.assertEqual(
            conn.wvm.reads,
            ["capabilities", ("/usr/bin/qemu-kvm", "x86_64", "q35", "kvm"), ("/usr/bin/qemu-kvm", "x86_64", "pc", "kvm")],
        )

    def test_the_overview_reads_the_info_once_and_the_free_memory_each_time(self):
        conn = connection(wvmHostDetails)
        conn.get_node_info()
        conn.get_memory_usage()
        self.assertEqual(conn.get_memory_usage()["total"], 2048 * 1048576)
        self.assertEqual(conn.wvm.reads, ["info", "memory", "memory"])

    def test_two_objects_do_not_share_their_reads(self):
        a, b = connection(), connection()
        a.get_cap_xml()
        b.get_cap_xml()
        self.assertEqual((a.wvm.reads, b.wvm.reads), (["capabilities"], ["capabilities"]))

    def test_a_failed_read_is_not_kept(self):
        conn = connection()
        conn.wvm.getCapabilities = lambda: (_ for _ in ()).throw(RuntimeError("libvirt error"))
        with self.assertRaises(RuntimeError):
            conn.get_cap_xml()
        conn.wvm = FakeConn()
        conn.get_cap_xml()
        self.assertEqual(conn.wvm.reads, ["capabilities"])


class NetDevicesTestCase(unittest.TestCase):
    def test_only_the_network_devices_are_listed_and_read(self):
        conn = connection()
        devices = {
            VIR_CONNECT_LIST_NODE_DEVICES_CAP_NET: [
                MagicMock(**{"XMLDesc.return_value": f"<device><capability type='net'><interface>{name}</interface>"
                                                     "<capability type='80203'/></capability></device>"})
                for name in ("eth0", "br0")
            ]
        }
        conn.wvm.listAllDevices = lambda flags: devices.get(flags, [])
        self.assertEqual(conn.get_net_devices(), ["eth0", "br0"])


class ChangeInterfacesTestCase(unittest.TestCase):
    def error(self, code):
        err = libvirtError("refused")
        err.get_error_code = lambda: code
        return err

    def test_a_backend_without_define_cannot_change_interfaces(self):
        conn = connection()
        # any other refusal (access denied, ...) leaves the page as it was
        for code, changeable in ((VIR_ERR_NO_SUPPORT, False), (VIR_ERR_XML_ERROR, True), (VIR_ERR_OPERATION_DENIED, True)):
            with self.subTest(code=code):
                conn.wvm.interfaceDefineXML = MagicMock(side_effect=self.error(code))
                self.assertIs(conn.can_change_interfaces(), changeable)
                # an invalid definition: nothing can be defined by asking
                conn.wvm.interfaceDefineXML.assert_called_once_with("<interface/>", 0)


class CapacityTestCase(unittest.TestCase):
    def test_a_host_gives_its_vms_cpus_and_memory(self):
        conn = connection(wvmHostDetails)
        gib = 1024 ** 3
        # get_host_instances gives the vCPUs as text, the memory in bytes
        conn.get_host_instances = MagicMock(return_value={
            "web": {"status": VIR_DOMAIN_RUNNING, "vcpu": "4", "memory": 4 * gib},
            "db": {"status": VIR_DOMAIN_PAUSED, "vcpu": "2", "memory": 2 * gib},
            "old": {"status": VIR_DOMAIN_SHUTOFF, "vcpu": "8", "memory": 8 * gib},
        })
        self.assertEqual(conn.get_capacity(), {
            "cpus": 4, "memory": 2 * gib,
            "vcpus": {"all": 14, "running": 6},
            "assigned": {"all": 14 * gib, "running": 6 * gib},
            "vms": {"running": 1, "paused": 1, "shutoff": 1, "other": 0},
        })
        conn.get_host_instances.assert_called_once_with(raw_mem_size=True)


class CpuTopologyTestCase(unittest.TestCase):
    """The topology comes from the capabilities' NUMA cells: getInfo makes
    one up (one node, one socket, every CPU a core) for hosts it cannot
    describe."""

    def topology(self, cells):
        conn = connection(wvmHostDetails)
        conn.__dict__["host_info"] = ["x86_64", 65536, 16, 2400, 1, 1, 16, 1]  # getInfo's made-up one
        conn.get_cap_xml = lambda: f"<capabilities><host><topology><cells num='2'>{cells}</cells></topology></host></capabilities>"
        return conn.get_cpu_topology()

    def test_sockets_and_cores_are_counted_from_the_cpus_of_the_numa_cells(self):
        # two nodes, two sockets, four cores of two threads each
        cells = "".join(
            f"<cell id='{node}'><cpus num='4'>"
            + "".join(f"<cpu id='{node * 4 + i}' socket_id='{node}' die_id='0' core_id='{i // 2}' siblings=''/>" for i in range(4))
            + "</cpus></cell>" for node in range(2))
        self.assertEqual(self.topology(cells), {"nodes": 2, "sockets": 2, "cores": 4, "cpus": 16, "mhz": 2400})

    def test_a_host_that_does_not_say_has_no_sockets_or_cores(self):
        cells = "<cell id='0'><cpus num='2'><cpu id='0'/><cpu id='1'/></cpus></cell>"
        self.assertEqual(self.topology(cells), {"nodes": 1, "sockets": None, "cores": None, "cpus": 16, "mhz": 2400})


class StoragesInfoTestCase(unittest.TestCase):
    def test_each_pool_tells_its_free_space(self):
        conn = connection(wvmStorages)
        pool = MagicMock(**{"isActive.return_value": 1, "XMLDesc.return_value": "<pool type='dir'/>",
                            "listVolumes.return_value": ["a.qcow2"], "info.return_value": [2, 500, 380, 120]})
        conn.get_storages = lambda: ["default"]
        conn.get_storage = lambda name: pool
        (info,) = conn.get_storages_info()
        self.assertEqual((info["name"], info["size"], info["free"], info["used_percent"]), ("default", 500, 120, 76))
        # measured now: libvirt keeps a pool's space as of its last refresh
        self.assertEqual([c[0] for c in pool.mock_calls[:2]], ["isActive", "refresh"])

    def test_a_pool_that_refuses_a_refresh_tells_its_last_space(self):
        conn = connection(wvmStorages)
        pool = MagicMock(**{"isActive.return_value": 1, "XMLDesc.return_value": "<pool type='dir'/>",
                            "listVolumes.return_value": [], "info.return_value": [2, 500, 380, 120],
                            "refresh.side_effect": libvirtError("pool is busy: a volume is cloned")})
        conn.get_storages = lambda: ["default"]
        conn.get_storage = lambda name: pool
        (info,) = conn.get_storages_info()
        self.assertEqual(info["free"], 120)

    def test_an_inactive_pool_is_not_refreshed(self):
        conn = connection(wvmStorages)
        pool = MagicMock(**{"isActive.return_value": 0, "XMLDesc.return_value": "<pool type='dir'/>",
                            "info.return_value": [0, 0, 0, 0]})
        conn.get_storages = lambda: ["off"]
        conn.get_storage = lambda name: pool
        conn.get_storages_info()
        pool.refresh.assert_not_called()
