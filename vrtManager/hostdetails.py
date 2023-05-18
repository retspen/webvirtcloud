import time

from vrtManager.connection import wvmConnect
from vrtManager.util import get_xml_path


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
        all_mem = self.wvm.getInfo()[1] * 1048576
        freemem = self.wvm.getMemoryStats(-1, 0)
        if isinstance(freemem, dict):
            free = (freemem["buffers"] + freemem["free"] + freemem["cached"]) * 1024
            percent = abs(100 - free * 100 // all_mem)
            usage = all_mem - free
            return {"total": all_mem, "usage": usage, "percent": percent}
        else:
            return {"total": None, "usage": None, "percent": None}

    def get_cpu_usage(self, diff=True):
        """
        Function return cpu usage on node.
        """
        prev_idle = 0
        prev_total = 0
        cpu = self.wvm.getCPUStats(-1, 0)
        if not isinstance(cpu, dict):
            return {"usage": None}

        for num in range(2):
            idle = self.wvm.getCPUStats(-1, 0)["idle"]
            total = sum(self.wvm.getCPUStats(-1, 0).values())
            diff_idle = idle - prev_idle
            diff_total = total - prev_total
            diff_usage = (1000 * (diff_total - diff_idle) / diff_total + 5) / 10
            if not diff:
                return {"usage": diff_usage}
            prev_total = total
            prev_idle = idle
            if num == 0:
                time.sleep(1)
            else:
                diff_usage = max(diff_usage, 0)

        return {"usage": diff_usage}

    def get_node_info(self):
        """
        Function return host server information: hostname, cpu, memory, ...
        """
        info = [self.wvm.getHostname()]  # hostname
        info.append(self.wvm.getInfo()[0])  # architecture
        info.append(self.wvm.getInfo()[1] * 1048576)  # memory
        info.append(self.wvm.getInfo()[2])  # cpu core count
        info.append(
            get_xml_path(self.wvm.getSysinfo(0), func=cpu_version)
        )  # cpu version
        info.append(self.wvm.getURI())  # uri
        return info
