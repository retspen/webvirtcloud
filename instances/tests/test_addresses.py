"""Finding the VMs that use an address (instances/addresses.py), with libvirt
answers faked per source."""

import threading
import time
import unittest
from ipaddress import ip_address, ip_network
from types import SimpleNamespace

from instances import addresses
from libvirt import (
    VIR_CONNECT_LIST_DOMAINS_ACTIVE,
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT,
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP,
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE,
    libvirtError,
)

AGENT, ARP, LEASE = (VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT, VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP,
                     VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)

MAC1 = "52:54:00:00:00:01"
MAC2 = "52:54:00:00:00:02"


def iface(mac, *addrs):
    """One interface of an interfaceAddresses answer: addrs are (type, addr, prefix)."""
    return {"hwaddr": mac, "addrs": [{"type": t, "addr": a, "prefix": p} for t, a, p in addrs]}


def domain_xml(*macs, agent=None, osinfo=None):
    nics = "".join(f"<interface type='bridge'><mac address='{mac}'/></interface>" for mac in macs)
    channel = ("<channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0' "
               f"state='{agent}'/></channel>") if agent else ""
    metadata = ("<metadata><libosinfo:libosinfo xmlns:libosinfo='http://libosinfo.org/xmlns/libvirt/domain/1.0'>"
                f"<libosinfo:os id='{osinfo}'/></libosinfo:libosinfo></metadata>") if osinfo else ""
    return f"<domain>{metadata}<devices>{nics}{channel}</devices></domain>"


class FakeDomain:
    """answers: source -> dict, an exception to raise, or an Event to wait on (a hung agent)."""

    def __init__(self, answers, uuid="uuid-a", name="vm-a", xml=None, state=1, os=None):
        self.answers, self.uuid, self.vname, self.state_, self.os = answers, uuid, name, state, os
        self.xml = xml or domain_xml(MAC1, agent="connected")

    def interfaceAddresses(self, source):
        answer = self.answers.get(source, {})
        if isinstance(answer, threading.Event):
            answer.wait()
            return {}
        if isinstance(answer, Exception):
            raise answer
        return answer

    def UUIDString(self):
        return self.uuid

    def name(self):
        return self.vname

    def state(self):
        return [self.state_, 0]

    def isActive(self):
        return self.state_ != 5

    def info(self):
        return [self.state_, 2097152, 1048576, 2, 0]  # max memory, memory (KiB), vCPUs

    def guestInfo(self, types=0, flags=0):
        if isinstance(self.os, threading.Event):
            self.os.wait()
            return {}
        if self.os is None:
            raise libvirtError("no guest agent")
        return self.os

    def XMLDesc(self, flags=0):
        return self.xml


def compute(name, *domains, pk=1, down=False):
    def listing(flags=0):
        return [d for d in domains if flags != VIR_CONNECT_LIST_DOMAINS_ACTIVE or d.state_ != 5]

    connection = SimpleNamespace(listAllDomains=listing)
    return SimpleNamespace(id=pk, name=name, status=not down or Exception("unreachable"), connection=connection)


def vm(uuid, mac, address, source=ARP, agent="connected"):
    return FakeDomain({source: {"eth0": iface(mac, (0, address, 24))}}, uuid=uuid, name=f"vm-{uuid}",
                      xml=domain_xml(mac, agent=agent))


class ReadAndMatchTests(unittest.TestCase):
    def test_a_query_is_an_address_or_a_network(self):
        self.assertEqual(addresses.parse_query(" 192.0.2.10 "), ip_network("192.0.2.10/32"))
        self.assertEqual(addresses.parse_query("192.0.2.7/24"), ip_network("192.0.2.0/24"))
        self.assertEqual(addresses.parse_query("2001:DB8::1"), ip_network("2001:db8::1/128"))
        for text in ("", "abc", "192.0.2.300"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                addresses.parse_query(text)

    def test_the_nics_and_the_agent_come_from_the_definition(self):
        xml = domain_xml(MAC1, MAC2.upper(), agent="connected")
        self.assertEqual(addresses.nic_macs(xml), {MAC1, MAC2})
        self.assertTrue(addresses.agent_connected(xml))
        self.assertFalse(addresses.agent_connected(domain_xml(MAC1, agent="disconnected")))
        self.assertFalse(addresses.agent_connected(domain_xml(MAC1)))

    def test_read_gives_each_address_with_its_mac(self):
        dom = FakeDomain({VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT: {
            "eth0": iface(MAC1, (0, "192.0.2.10", 24), (1, "2001:db8::10", 64), (1, "fe80::1", 64)),
        }})
        self.assertEqual(addresses.read(dom, VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT),
                         [(MAC1, ip_address("192.0.2.10")), (MAC1, ip_address("2001:db8::10")),
                          (MAC1, ip_address("fe80::1"))])
        failing = FakeDomain({VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP: libvirtError("no ARP")})
        self.assertIsNone(addresses.read(failing, VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP))

    def test_an_interface_without_a_mac_is_skipped(self):
        # the agent gives tunnels (wg0, tun0) no hardware address: libvirt's hwaddr is None
        dom = FakeDomain({AGENT: {"wg0": {"hwaddr": None, "addrs": [{"type": 0, "addr": "198.51.100.5", "prefix": 32}]},
                                  "eth0": iface(MAC1, (0, "192.0.2.10", 24))}})
        self.assertEqual(addresses.read(dom, AGENT), [(MAC1, ip_address("192.0.2.10"))])


class FindTests(unittest.TestCase):
    def find(self, *targets, query="192.0.2.10", deadline=5.0):
        return addresses.find(list(targets), addresses.parse_query(query), deadline=deadline)

    def test_an_address_is_found_with_all_its_sources(self):
        dom = FakeDomain({ARP: {"e": iface(MAC1, (0, "192.0.2.10", 24))},
                          AGENT: {"eth0": iface(MAC1, (0, "192.0.2.10", 24))}})
        (match,) = self.find(addresses.Target(compute("c1", dom), None))["matches"]
        self.assertEqual((match["uuid"], match["mac"], match["address"]), ("uuid-a", MAC1, "192.0.2.10"))
        self.assertEqual(match["sources"], ["ARP", "agent"])
        self.assertFalse(match["conflict"])

    def test_a_network_lists_every_address_in_it_sorted(self):
        c = compute("c1", vm("a", MAC1, "192.0.2.30"), vm("b", MAC2, "192.0.2.4"),
                    vm("c", "52:54:00:00:00:03", "198.51.100.1"))
        result = self.find(addresses.Target(c, None), query="192.0.2.0/24")
        self.assertEqual([m["address"] for m in result["matches"]], ["192.0.2.4", "192.0.2.30"])

    def test_two_vms_with_one_address_are_a_conflict(self):
        c = compute("c1", vm("a", MAC1, "192.0.2.10"), vm("b", MAC2, "192.0.2.10", source=LEASE))
        matches = self.find(addresses.Target(c, None))["matches"]
        self.assertEqual([(m["uuid"], m["conflict"]) for m in matches], [("a", True), ("b", True)])

    def test_a_guest_interface_that_is_not_a_nic_never_matches(self):
        dom = FakeDomain({AGENT: {"docker0": iface("02:42:ac:11:00:01", (0, "198.51.100.77", 16))}})
        self.assertEqual(self.find(addresses.Target(compute("c1", dom), None), query="198.51.100.77")["matches"], [])

    def test_owners_see_only_their_vms(self):
        c = compute("c1", vm("uuid-a", MAC1, "192.0.2.10"), vm("uuid-b", MAC2, "192.0.2.10"))
        matches = self.find(addresses.Target(c, {"uuid-a"}))["matches"]
        self.assertEqual([m["uuid"] for m in matches], ["uuid-a"])

    def test_a_vm_without_a_connected_agent_is_counted(self):
        c = compute("c1", vm("a", MAC1, "192.0.2.10"), vm("b", MAC2, "192.0.2.11", agent="disconnected"))
        result = self.find(addresses.Target(c, None))
        self.assertEqual((result["checked"], result["no_agent"]), (2, 1))

    def test_a_hung_agent_does_not_hold_the_answer(self):
        hung = threading.Event()
        try:
            stuck = FakeDomain({AGENT: hung}, uuid="hung", xml=domain_xml(MAC2, agent="connected"))
            c = compute("c1", vm("a", MAC1, "192.0.2.10"), stuck)
            started = time.monotonic()
            result = self.find(addresses.Target(c, None), deadline=0.3)
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual([m["uuid"] for m in result["matches"]], ["a"])
            self.assertEqual(result["unread"], 1)
        finally:
            hung.set()

    def test_a_down_host_is_reported_and_the_others_answer(self):
        up = compute("c1", vm("a", MAC1, "192.0.2.10"))
        down = compute("c2", vm("b", MAC2, "192.0.2.10"), pk=2, down=True)
        result = self.find(addresses.Target(up, None), addresses.Target(down, None))
        self.assertEqual(result["hosts_down"], ["c2"])
        self.assertEqual([m["uuid"] for m in result["matches"]], ["a"])

    def test_slow_down_hosts_are_waited_for_together(self):
        # connecting to an unreachable host takes the connect timeout: on the
        # compute's own thread, two of them cost one timeout, not two
        class Slow(SimpleNamespace):
            @property
            def status(self):
                time.sleep(0.3)
                return Exception("unreachable")

        started = time.monotonic()
        result = self.find(addresses.Target(Slow(id=1, name="c1"), None), addresses.Target(Slow(id=2, name="c2"), None))
        self.assertLess(time.monotonic() - started, 0.55)
        self.assertEqual(result["hosts_down"], ["c1", "c2"])

    def test_too_many_running_searches_are_refused(self):
        addresses._running = addresses.MAX_RUNNING
        try:
            with self.assertRaises(addresses.Busy):
                self.find(addresses.Target(compute("c1"), None))
        finally:
            addresses._running = 0

    def test_a_link_local_address_matches_a_link_local_query(self):
        dom = FakeDomain({AGENT: {"eth0": iface(MAC1, (1, "fe80::1234", 64))}})
        (match,) = self.find(addresses.Target(compute("c1", dom), None), query="fe80::1234")["matches"]
        self.assertEqual(match["address"], "fe80::1234")

    def test_a_vm_that_vanishes_keeps_the_hosts_other_results(self):
        class Gone(FakeDomain):
            def XMLDesc(self, flags=0):
                raise libvirtError("Domain not found")

        c = compute("c1", Gone({}, uuid="gone"), vm("a", MAC1, "192.0.2.10"))
        result = self.find(addresses.Target(c, None))
        self.assertEqual(result["hosts_down"], [])
        self.assertEqual([m["uuid"] for m in result["matches"]], ["a"])

    def test_a_slow_host_is_unfinished_not_down(self):
        slow = threading.Event()
        try:
            def listing(flags=0):
                slow.wait()
                return []

            c = SimpleNamespace(id=2, name="c2", status=True, connection=SimpleNamespace(listAllDomains=listing))
            result = self.find(addresses.Target(compute("c1", vm("a", MAC1, "192.0.2.10")), None),
                               addresses.Target(c, None), deadline=0.3)
            self.assertEqual((result["hosts_down"], result["hosts_unfinished"]), ([], ["c2"]))
            self.assertEqual([m["uuid"] for m in result["matches"]], ["a"])
        finally:
            slow.set()

    def test_a_search_needs_room_for_all_its_threads(self):
        addresses._running = addresses.MAX_RUNNING - addresses.MAX_WORKERS + 1
        try:
            with self.assertRaises(addresses.Busy):
                self.find(addresses.Target(compute("c1"), None))
        finally:
            addresses._running = 0

    def test_a_failed_agent_read_is_not_a_read(self):
        dom = FakeDomain({AGENT: libvirtError("guest-network-get-interfaces is disabled")})
        result = self.find(addresses.Target(compute("c1", dom), None))
        self.assertEqual(result["unread"], 1)

    def test_a_vm_on_two_computes_is_two_vms(self):
        # one UUID on two hosts (a copied definition): rows and conflicts keep them apart
        result = self.find(addresses.Target(compute("c1", vm("same", MAC1, "192.0.2.10")), None),
                           addresses.Target(compute("c2", vm("same", MAC2, "192.0.2.10"), pk=2), None))
        self.assertEqual([(m["compute_id"], m["conflict"]) for m in result["matches"]], [(1, True), (2, True)])


class InventoryTests(unittest.TestCase):
    """Every VM of the targets, one row each, for the report."""

    def test_every_vm_comes_with_its_addresses_and_os(self):
        running = FakeDomain({ARP: {"e": iface(MAC1, (0, "192.0.2.10", 24))},
                              AGENT: {"eth0": iface(MAC1, (0, "192.0.2.10", 24), (1, "2001:db8::10", 64))}},
                             uuid="a", name="web", os={"os.id": "almalinux", "os.pretty-name": "AlmaLinux 10.0"})
        off = FakeDomain({}, uuid="b", name="win", state=5,
                         xml=domain_xml(MAC2, osinfo="http://microsoft.com/win/2k22"))
        result = addresses.inventory([addresses.Target(compute("c1", running, off), None)])
        web, win = result["vms"]
        self.assertEqual((web["name"], web["state"], web["vcpus"], web["memory"]), ("web", 1, 2, 1024))
        self.assertEqual((web["os"], web["os_family"]), ("AlmaLinux 10.0", "Linux"))
        self.assertEqual(web["macs"], [MAC1])
        self.assertEqual(web["addresses"], [("192.0.2.10", ["ARP", "agent"]), ("2001:db8::10", ["agent"])])
        self.assertEqual((win["name"], win["state"], win["addresses"]), ("win", 5, []))
        self.assertEqual((win["os"], win["os_family"]), ("win 2k22", "Windows"))

    def test_an_os_without_an_agent_or_metadata_is_unknown(self):
        dom = vm("a", MAC1, "192.0.2.10", agent=None)
        (row,) = addresses.inventory([addresses.Target(compute("c1", dom), None)])["vms"]
        self.assertEqual((row["os"], row["os_family"]), ("", ""))

    def test_an_agent_that_reports_no_os_falls_back_to_the_metadata(self):
        dom = FakeDomain({}, xml=domain_xml(MAC1, agent="connected", osinfo="http://almalinux.org/almalinux/9"))
        (row,) = addresses.inventory([addresses.Target(compute("c1", dom), None)])["vms"]
        self.assertEqual((row["os"], row["os_family"]), ("almalinux 9", "Linux"))

    def test_a_down_host_and_a_late_agent_are_counted(self):
        hung = threading.Event()
        try:
            stuck = FakeDomain({AGENT: hung}, uuid="hung", xml=domain_xml(MAC2, agent="connected"))
            result = addresses.inventory([addresses.Target(compute("c1", stuck), None),
                                          addresses.Target(compute("c2", pk=2, down=True), None)], deadline=0.3)
            self.assertEqual((result["hosts_down"], result["unread"]), (["c2"], 1))
            self.assertEqual([row["name"] for row in result["vms"]], ["vm-a"])
        finally:
            hung.set()

    def test_an_os_read_that_hangs_keeps_the_addresses_read(self):
        hung = threading.Event()
        try:
            dom = FakeDomain({AGENT: {"eth0": iface(MAC1, (0, "192.0.2.10", 24))}}, os=hung)
            result = addresses.inventory([addresses.Target(compute("c1", dom), None)], deadline=0.3)
            (row,) = result["vms"]
            self.assertEqual(row["addresses"], [("192.0.2.10", ["agent"])])
            self.assertEqual(result["unread"], 0)
        finally:
            hung.set()
