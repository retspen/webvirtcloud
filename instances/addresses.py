"""
The VMs that use an IP address or an address in a network, and an inventory
of every VM with its addresses and operating system, read live from
libvirt: DHCP leases of libvirt's networks, the host's ARP table, and the
guest agent. An address counts only on one of the VM's own NICs (by MAC), so
interfaces inside the guest such as docker0 never match.
"""

import re
import threading
import time
from concurrent import futures
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

from libvirt import (
    VIR_CONNECT_LIST_DOMAINS_ACTIVE,
    VIR_DOMAIN_GUEST_INFO_OS,
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


MAC = re.compile(r"[0-9a-f]{2}([:-]?)[0-9a-f]{2}(\1[0-9a-f]{2}){4}")


def parse_mac(text):
    """A MAC address (aa:bb:..., aa-bb-..., aabb...) in lower-case colon form; None otherwise."""
    text = text.strip().lower()
    if not MAC.fullmatch(text):
        return None
    digits = text.replace(":", "").replace("-", "")
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


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


def os_family(name):
    """Windows, FreeBSD or Linux, from a guest agent's OS id or a libosinfo
    URL's host; "" for none."""
    if not name:
        return ""
    if "microsoft" in name or name == "mswindows":
        return "Windows"
    if "freebsd" in name:
        return "FreeBSD"
    return "Linux"


def defined_os(xml):
    """(name, family) of the libosinfo id a tool such as virt-install wrote
    into the definition (http://almalinux.org/almalinux/9: almalinux 9)."""
    ids = etree.fromstring(xml).xpath("/domain/metadata/*[local-name()='libosinfo']/*[local-name()='os']/@id")
    if not ids:
        return "", ""
    url = urlparse(ids[0])
    return " ".join(url.path.strip("/").split("/")), os_family(url.netloc)


def _matching(dom, vm, source, macs, network):
    """The source's addresses on the domain's own NICs (in the network, if
    one is given), as (vm, MAC, address, source) observations; vm is
    (compute id, UUID, name). None if the source could not be read."""
    pairs = read(dom, source)
    if pairs is None:
        return None
    return [(vm, mac, address, source) for mac, address in pairs
            if mac in macs and (network is None or address in network)]


def _read_os(dom):
    """The guest agent's OS as (name, family); None if it gives none."""
    try:
        info = dom.guestInfo(VIR_DOMAIN_GUEST_INFO_OS)
    except libvirtError:
        return None
    if not info.get("os.id"):
        return None
    return info.get("os.pretty-name") or info.get("os.name") or info["os.id"], os_family(info["os.id"])


def _read_host(target, network, everything, mac):
    """The cheap first phase on one compute: leases and ARP of each running
    VM in scope (with everything, the shut-off ones are listed too). Returns
    the VMs' records, the observations, the (domain, vm, MACs) whose agent is
    to be asked, the number of running VMs read and of those without a
    connected agent; None when the compute cannot be reached (connecting may
    take the connect timeout, so this too runs on the compute's thread). A
    VM that stops or leaves meanwhile is skipped. With a mac, only the VMs
    with a NIC of that MAC, and only that NIC's addresses."""
    if target.compute.status is not True:
        return None
    records, found, agents, checked, no_agent = [], [], [], 0, 0
    listing = 0 if everything else VIR_CONNECT_LIST_DOMAINS_ACTIVE
    for dom in target.compute.connection.listAllDomains(listing):
        try:
            uuid = dom.UUIDString()
            if target.uuids is not None and uuid not in target.uuids:
                continue
            vm = (target.compute.id, uuid, dom.name())
            xml = dom.XMLDesc(0)
            state, _, memory, vcpus, _ = dom.info()
            active = dom.isActive()
        except libvirtError:
            continue
        macs = nic_macs(xml)
        if mac:
            if mac not in macs:
                continue
            macs = {mac}
        os, family = defined_os(xml)
        records.append({"vm": vm, "state": state, "vcpus": vcpus, "memory": memory // 1024,
                        "macs": sorted(macs), "os": os, "os_family": family})
        if not active:
            continue
        checked += 1
        for source in (VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE, VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP):
            found += _matching(dom, vm, source, macs, network) or []
        if not agent_connected(xml):
            no_agent += 1
        elif state == VIR_DOMAIN_RUNNING:  # a paused guest cannot answer
            agents.append((dom, vm, macs))
    return records, found, agents, checked, no_agent
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


def _survey(targets, network, deadline, everything, with_os=False, mac=None):
    """
    Read the targets by the deadline (seconds): first each compute's VMs,
    leases and ARP, then each VM's guest agent on its own thread, so a hung
    agent holds back only its VM. What was not read in time is counted, not
    waited for: hosts not reached, hosts not finished, and agents not read
    (late or failed). Returns the VMs' records, the observations, the agents'
    OS by vm, and the counts.
    """
    if _running > MAX_RUNNING - MAX_WORKERS:
        raise Busy
    end = time.monotonic() + deadline
    records, observations, hosts_down, agent_reads, os_reads, systems = [], [], [], [], {}, {}
    checked = no_agent = unread = 0
    pool = futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        hosts = {pool.submit(_counted, _read_host, target, network, everything, mac): target.compute
                 for target in targets}
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
                host_records, found, agents, host_checked, host_no_agent = read_host
                records += host_records
                observations += found
                checked += host_checked
                no_agent += host_no_agent
                # the OS on its own thread: a hung OS read keeps the addresses read
                for dom, vm, macs in agents:
                    agent_reads.append(pool.submit(_counted, _matching, dom, vm,
                                                   VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT, macs, network))
                    if with_os:
                        os_reads[pool.submit(_counted, _read_os, dom)] = vm
        except futures.TimeoutError:
            pass
        futures.wait(agent_reads + list(os_reads), timeout=max(0, end - time.monotonic()))
        for done in agent_reads:
            found = done.result() if done.done() and not done.cancelled() else None
            if found is None:
                unread += 1
            else:
                observations += found
        for done, vm in os_reads.items():
            if done.done() and not done.cancelled() and done.result():
                systems[vm] = done.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return records, observations, systems, {
        "checked": checked, "no_agent": no_agent, "unread": unread, "hosts_down": sorted(hosts_down),
        "hosts_unfinished": sorted(hosts[future].name for future in waiting)}


def find(targets, network, deadline=5.0):
    """The running VMs of the targets with an address in the network, one
    row per VM, MAC and address, with what could not be read."""
    _, observations, _, counts = _survey(targets, network, deadline, everything=False)
    return {"matches": _rows(observations), **counts}


def find_mac(targets, mac, deadline=5.0):
    """The VMs of the targets with a NIC of the MAC, shut-off ones too, one
    row per VM and address of that NIC (one row without an address if it
    has none). One MAC on more than one VM is a conflict."""
    records, observations, _, counts = _survey(targets, None, deadline, everything=True, mac=mac)
    found = {}
    for row in _rows(observations):
        if not ip_address(row["address"]).is_link_local:  # made from the MAC: not a finding
            found.setdefault((row["compute_id"], row["uuid"]), []).append(row)
    conflict = len({record["vm"][:2] for record in records}) > 1
    matches = []
    for record in sorted(records, key=lambda record: (record["vm"][2], record["vm"][0])):
        compute_id, uuid, name = record["vm"]
        rows = found.get((compute_id, uuid)) or [
            {"compute_id": compute_id, "uuid": uuid, "name": name, "mac": mac, "address": "", "sources": []}]
        matches += [{**row, "conflict": conflict} for row in rows]
    return {"matches": matches, **counts}


def inventory(targets, deadline=20.0):
    """Every VM of the targets, shut-off ones too, with its addresses and OS
    (the agent's, else the definition's libosinfo id), sorted by name."""
    records, observations, systems, counts = _survey(targets, None, deadline, everything=True, with_os=True)
    addresses = {}
    for row in _rows(observations):
        vm = (row["compute_id"], row["uuid"], row["name"])
        addresses.setdefault(vm, []).append((row["address"], row["sources"]))
    vms = []
    for record in records:
        vm = record.pop("vm")
        os, family = systems.get(vm, (record["os"], record["os_family"]))
        vms.append({"compute_id": vm[0], "uuid": vm[1], "name": vm[2], **record, "os": os, "os_family": family,
                    "addresses": addresses.get(vm, [])})
    vms.sort(key=lambda row: (row["name"], row["compute_id"]))
    return {"vms": vms, **counts}
