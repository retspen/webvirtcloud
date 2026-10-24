"""
The VMs that use an IP address or an address in a network, read live from
libvirt: DHCP leases of libvirt's networks, the host's ARP table, and the
guest agent. An address counts only on one of the VM's own NICs (by MAC), so
interfaces inside the guest such as docker0 never match.
"""

import threading
import time
from concurrent import futures
from dataclasses import dataclass
from ipaddress import ip_address, ip_network

from libvirt import (
    VIR_CONNECT_LIST_DOMAINS_ACTIVE,
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT,
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP,
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE,
    VIR_DOMAIN_RUNNING,
    libvirtError,
)
from lxml import etree

# in the order a match lists its sources
SOURCES = {
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE: "lease",
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP: "ARP",
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT: "agent",
}

# A search asks the hosts in parallel, at most MAX_WORKERS threads at once.
# A guest agent may never answer (libvirt waits without limit by default):
# its thread stays blocked after the search answers (and holds up the
# worker's exit until it does), so a search starts only while its threads
# fit in MAX_RUNNING search threads in this process.
MAX_WORKERS = 8
MAX_RUNNING = 16
_running = 0
_running_lock = threading.Lock()


class Busy(Exception):
    pass


@dataclass
class Target:
    """A compute to search, and the UUIDs of its VMs to search; None for all of them."""
    compute: object
    uuids: set | None


def parse_query(text):
    """An address as a one-address network, or a network; ValueError otherwise."""
    return ip_network(text.strip(), strict=False)


def nic_macs(xml):
    return {mac.lower() for mac in etree.fromstring(xml).xpath("/domain/devices/interface/mac/@address")}


def agent_connected(xml):
    states = etree.fromstring(xml).xpath(
        "/domain/devices/channel/target[@name='org.qemu.guest_agent.0']/@state")
    return states == ["connected"]


def read(dom, source):
    """(MAC, address) pairs the source reports for the domain's interfaces
    that have a MAC (an agent's tunnels have none); None if it fails."""
    try:
        answer = dom.interfaceAddresses(source)
    except libvirtError:
        return None
    return [(iface["hwaddr"].lower(), ip_address(addr["addr"]))
            for iface in answer.values() if iface.get("hwaddr")
            for addr in iface.get("addrs") or []]


def _counted(func, *args):
    global _running
    with _running_lock:
        _running += 1
    try:
        return func(*args)
    finally:
        with _running_lock:
            _running -= 1


def _matching(dom, vm, source, macs, network):
    """The source's addresses in the network on the domain's own NICs, as
    (vm, MAC, address, source) observations; vm is (compute id, UUID, name).
    None if the source could not be read."""
    pairs = read(dom, source)
    if pairs is None:
        return None
    return [(vm, mac, address, source) for mac, address in pairs if mac in macs and address in network]


def _read_host(target, network):
    """The cheap first phase on one compute: leases and ARP of each running VM
    in scope. Returns the observations, the (domain, vm, MACs) whose agent is
    to be asked, the number of VMs read and of those without a connected
    agent; None when the compute cannot be reached (connecting may take the
    connect timeout, so this too runs on the compute's thread). A VM that
    stops or leaves meanwhile is skipped."""
    if target.compute.status is not True:
        return None
    found, agents, checked, no_agent = [], [], 0, 0
    for dom in target.compute.connection.listAllDomains(VIR_CONNECT_LIST_DOMAINS_ACTIVE):
        try:
            uuid = dom.UUIDString()
            if target.uuids is not None and uuid not in target.uuids:
                continue
            vm = (target.compute.id, uuid, dom.name())
            xml = dom.XMLDesc(0)
            running = dom.state()[0] == VIR_DOMAIN_RUNNING  # a paused guest cannot answer
        except libvirtError:
            continue
        macs = nic_macs(xml)
        checked += 1
        for source in (VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE, VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP):
            found += _matching(dom, vm, source, macs, network) or []
        if not agent_connected(xml):
            no_agent += 1
        elif running:
            agents.append((dom, vm, macs))
    return found, agents, checked, no_agent


def _rows(observations):
    """One row per VM, MAC and address with its sources; sorted by address.
    A VM is its compute and UUID: one UUID may be defined on two hosts."""
    sources = {}
    for vm, mac, address, source in observations:
        sources.setdefault((vm, mac, address), set()).add(source)
    users = {}
    for vm, _, address in sources:
        users.setdefault(address, set()).add(vm[:2])
    rows = [{"compute_id": vm[0], "uuid": vm[1], "name": vm[2], "mac": mac, "address": str(address),
             "sources": [SOURCES[s] for s in SOURCES if s in found], "conflict": len(users[address]) > 1,
             "_key": (address.version, address, vm[2], vm[0])}
            for (vm, mac, address), found in sources.items()]
    rows.sort(key=lambda row: row.pop("_key"))
    return rows


def find(targets, network, deadline=5.0):
    """
    The running VMs of the targets with an address in the network, read by
    the deadline (seconds). First each compute's leases and ARP, then each
    VM's guest agent on its own thread, so a hung agent holds back only its
    VM. What was not read in time is counted, not waited for: hosts not
    reached, hosts not finished, and agents not read (late or failed).
    """
    if _running > MAX_RUNNING - MAX_WORKERS:
        raise Busy
    end = time.monotonic() + deadline
    observations, hosts_down, agent_reads = [], [], []
    checked = no_agent = unread = 0
    pool = futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        hosts = {pool.submit(_counted, _read_host, target, network): target.compute for target in targets}
        waiting = set(hosts)
        try:
            for done in futures.as_completed(hosts, timeout=max(0, end - time.monotonic())):
                waiting.discard(done)
                try:
                    read_host = done.result()
                except libvirtError:
                    read_host = None
                if read_host is None:
                    hosts_down.append(hosts[done].name)
                    continue
                found, agents, host_checked, host_no_agent = read_host
                observations += found
                checked += host_checked
                no_agent += host_no_agent
                agent_reads += [pool.submit(_counted, _matching, dom, vm,
                                            VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT, macs, network)
                                for dom, vm, macs in agents]
        except futures.TimeoutError:
            pass
        finished, late = futures.wait(agent_reads, timeout=max(0, end - time.monotonic()))
        unread = len(late)
        for done in finished:
            found = done.result()
            if found is None:
                unread += 1
            else:
                observations += found
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return {"matches": _rows(observations), "checked": checked, "no_agent": no_agent, "unread": unread,
            "hosts_down": sorted(hosts_down), "hosts_unfinished": sorted(hosts[f].name for f in waiting)}
