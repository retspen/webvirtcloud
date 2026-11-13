import time

from libvirt import (
    libvirtError,
    VIR_CONNECT_GET_ALL_DOMAINS_STATS_NOWAIT,
    VIR_DOMAIN_BLOCKED,
    VIR_DOMAIN_PAUSED,
    VIR_DOMAIN_RUNNING,
    VIR_DOMAIN_SHUTOFF,
    VIR_DOMAIN_STATS_BALLOON,
    VIR_DOMAIN_STATS_STATE,
    VIR_DOMAIN_STATS_VCPU,
    VIR_NODE_CPU_STATS_ALL_CPUS,
)
from lxml import etree

from vrtManager.connection import wvmConnect
from vrtManager.util import get_xml_path


# a VM's state as the host's VM counts group it; others count as "other"
VM_STATES = {
    VIR_DOMAIN_RUNNING: "running",
    VIR_DOMAIN_BLOCKED: "running",  # running, waiting on a resource
    VIR_DOMAIN_PAUSED: "paused",
    VIR_DOMAIN_SHUTOFF: "shutoff",
}

# the times of virNodeGetCPUStats that add up to the elapsed CPU time; guest is
# already part of user and utilization is a percentage
CPU_TIMES = ("kernel", "user", "idle", "iowait")


def cpu_percent(before, after):
    """Busy share in percent between two (idle, total) samples, or None when
    the second does not follow the first."""
    idle = after[0] - before[0]
    total = after[1] - before[1]
    if total <= 0 or not 0 <= idle <= total:
        return None
    return round(100 * (total - idle) / total, 1)


def cpu_version(doc):
    for info in doc.xpath("/sysinfo/processor/entry"):
        elem = info.xpath("@name")[0]
        if elem == "version":
            return info.text
    return "Unknown"


class wvmHostDetails(wvmConnect):
    def get_memory_usage(self):
        """
        Function return memory usage on node.
        """
        all_mem = self.host_info[1] * 1048576
        freemem = self.wvm.getMemoryStats(-1, 0)
        if isinstance(freemem, dict):
            free = (freemem["buffers"] + freemem["free"] + freemem["cached"]) * 1024
            percent = abs(100 - free * 100 // all_mem)
            usage = all_mem - free
            return {"total": all_mem, "usage": usage, "percent": percent}
        else:
            return {"total": None, "usage": None, "percent": None}

    def _cpu_times(self):
        """(idle, total) nanoseconds of all host CPUs, from one reading. Time
        waiting for I/O is idle: no CPU runs then, it only waits for disks."""
        stats = self.wvm.getCPUStats(VIR_NODE_CPU_STATS_ALL_CPUS, 0)
        return stats["idle"] + stats.get("iowait", 0), sum(stats.get(name, 0) for name in CPU_TIMES)

    def get_cpu_usage(self, previous=None):
        """
        Busy share of all host CPUs in percent since previous, an (idle, total,
        time) sample this method returned, or over one second when there is
        none or it does not lead to this one (the host restarted). Also returns
        the closing sample and the seconds the usage covers.
        """
        times = self._cpu_times()
        now = time.monotonic()  # elapsed time: a clock set back would make it negative
        usage = None
        if previous is not None and previous[2] < now:  # else from before the server restarted
            usage = cpu_percent(previous[:2], times)
            start = previous[2]
        if usage is None:
            before, start = times, now
            time.sleep(1)
            times = self._cpu_times()
            now = time.monotonic()
            usage = cpu_percent(before, times)
        return {"usage": usage, "sample": (*times, now), "window": now - start}

    def get_node_info(self):
        """
        Function return host server information: hostname, cpu, memory, ...
        """
        info = [self.wvm.getHostname()]  # hostname
        info.append(self.host_info[0])  # architecture
        info.append(self.host_info[1] * 1048576)  # memory
        info.append(self.host_info[2])  # cpu core count
        try:
            info.append(get_xml_path(self.wvm.getSysinfo(0), func=cpu_version))  # cpu version
        except libvirtError:  # not every driver or host gives its sysinfo
            info.append(None)
        info.append(self.wvm.getURI())  # uri
        return info

    def get_capacity(self):
        """
        What the host has given its VMs: vCPUs and memory (bytes) of all VMs
        and of the running ones (paused ones too: they keep theirs), against
        its CPUs and memory. A shut-off VM takes its share again when it
        starts. Also its VMs by state: running, paused, shut off and other
        (crashed, suspended, shutting down).
        """
        vcpus = {"all": 0, "running": 0}
        assigned = {"all": 0, "running": 0}
        vms = {"running": 0, "paused": 0, "shutoff": 0, "other": 0}
        for state, memory, vcpu in self._domain_sizes():
            for share in ("all",) if state == VIR_DOMAIN_SHUTOFF else ("all", "running"):
                vcpus[share] += vcpu
                assigned[share] += memory * 1024
            vms[VM_STATES.get(state, "other")] += 1
        return {"cpus": self.host_info[2], "memory": self.host_info[1] * 1048576,
                "vcpus": vcpus, "assigned": assigned, "vms": vms}

    def _domain_sizes(self):
        """Each VM's state, memory (KiB) and vCPUs, in one call: not its XML,
        one round trip a VM. A running VM busy with a job (a migration, a
        hung QEMU) is not waited for: its sizes come from its XML."""
        flags = VIR_DOMAIN_STATS_STATE | VIR_DOMAIN_STATS_BALLOON | VIR_DOMAIN_STATS_VCPU
        for dom, stats in self.wvm.getAllDomainStats(flags, VIR_CONNECT_GET_ALL_DOMAINS_STATS_NOWAIT):
            memory, vcpu = stats.get("balloon.current"), stats.get("vcpu.current")
            if memory is None or vcpu is None:
                try:
                    doc = etree.fromstring(dom.XMLDesc(0))
                except libvirtError:
                    continue  # gone meanwhile
                memory, vcpu = int(doc.findtext("currentMemory")), doc.find("vcpu")
                vcpu = int(vcpu.get("current", vcpu.text))
            yield stats["state.state"], memory, vcpu

    def get_cpu_topology(self):
        """
        The host's logical CPUs and MHz, and from the CPUs of its NUMA cells
        in its capabilities, the NUMA nodes, sockets and physical cores (None
        when it does not say). Not virNodeGetInfo's topology: it makes one up
        for hosts it cannot describe, such as asymmetric NUMA.
        """

        def topology(doc):
            cpus = doc.xpath("/capabilities/host/topology/cells/cell/cpus/cpu[@socket_id]")
            return {
                "nodes": len(doc.xpath("/capabilities/host/topology/cells/cell")) or None,
                "sockets": len({cpu.get("socket_id") for cpu in cpus}) or None,
                # a core is one within its socket and die
                "cores": len({(cpu.get("socket_id"), cpu.get("die_id"), cpu.get("core_id")) for cpu in cpus}) or None,
            }

        return {**get_xml_path(self.get_cap_xml(), func=topology), "cpus": self.host_info[2], "mhz": self.host_info[3]}
