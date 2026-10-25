import time

from libvirt import VIR_DOMAIN_SHUTOFF, VIR_NODE_CPU_STATS_ALL_CPUS

from vrtManager.connection import wvmConnect
from vrtManager.util import get_xml_path


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
        """(idle, total) nanoseconds of all host CPUs, from one reading."""
        stats = self.wvm.getCPUStats(VIR_NODE_CPU_STATS_ALL_CPUS, 0)
        return stats["idle"], sum(stats.get(name, 0) for name in CPU_TIMES)

    def get_cpu_usage(self, previous=None):
        """
        Busy share of all host CPUs in percent since previous, an (idle, total,
        time) sample this method returned, or over one second when there is
        none or it does not lead to this one (the host restarted). Also returns
        the closing sample and the seconds the usage covers.
        """
        times = self._cpu_times()
        now = time.time()
        usage = None
        if previous is not None:
            usage = cpu_percent(previous[:2], times)
            start = previous[2]
        if usage is None:
            before, start = times, now
            time.sleep(1)
            times = self._cpu_times()
            now = time.time()
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
        info.append(
            get_xml_path(self.wvm.getSysinfo(0), func=cpu_version)
        )  # cpu version
        info.append(self.wvm.getURI())  # uri
        return info

    def get_capacity(self):
        """
        What the host has given its VMs: vCPUs and memory (bytes) of all VMs
        and of the running ones, against its CPUs and memory. A shut-off VM
        takes its share again when it starts.
        """
        vcpus = {"all": 0, "running": 0}
        assigned = {"all": 0, "running": 0}
        for vm in self.get_host_instances(raw_mem_size=True).values():
            for share in ("all",) if vm["status"] == VIR_DOMAIN_SHUTOFF else ("all", "running"):
                vcpus[share] += int(vm["vcpu"])
                assigned[share] += vm["memory"]
        return {"cpus": self.host_info[2], "memory": self.host_info[1] * 1048576,
                "vcpus": vcpus, "assigned": assigned}
