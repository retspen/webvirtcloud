import time
from libvmgr import util
from libvmgr.connect import wvcConnect


class wvcHost(wvcConnect):
    def __init__(self, conn):
        self.conn = conn

    def get_node_info(self):
        """
        Function return host server information: hostname, cpu, memory, ...
        """
        info = list()
        info.append(self.conn.getHostname())
        info.append(self.conn.getInfo()[0])
        info.append(self.conn.getInfo()[1] * (1024**2))
        info.append(self.conn.getInfo()[2])
        info.append(util.get_xml_data(self.conn.getSysinfo(0), 'processor/entry[6]'))
        info.append(self.conn.getURI())
        return info

    def hypervisor_type(self):
        """
        Return hypervisor type
        """
        return util.get_xml_data(self.get_cap_xml(), 'guest/arch/domain', 'type')

    def get_memory_usage(self):
        """
        Function return memory usage on node.
        """
        host_mem = self.conn.getInfo()[1] * (1024**2)
        free_mem = self.conn.getMemoryStats(-1, 0)
        if isinstance(free_mem, dict):
            mem = list(free_mem.values())
            free = (mem[1] + mem[2] + mem[3]) * 1024
            percent = (100 - ((free * 100) / host_mem))
            usage = (host_mem - free)
            mem_usage = {'size': host_mem, 'usage': usage, 'percent': round(percent)}
        else:
            mem_usage = {'size': 0, 'usage': 0, 'percent': 0}
        return mem_usage

    def get_storage_usage(self, name):
        """
        Function return storage usage on node by name.
        """
        pool = self.get_storage(name)
        pool.refresh()
        if pool.isActive():
            size = pool.info()[1]
            free = pool.info()[3]
            used = size - free
            percent = (used * 100) / size
            return {'size': size, 'used': used, 'percent': percent}
        else:
            return {'size': 0, 'used': 0, 'percent': 0}

    def get_cpu_usage(self):
        """
        Function return cpu usage on node.
        """
        prev_idle = 0
        prev_total = 0
        diff_usage = 0
        cpu = self.conn.getCPUStats(-1, 0)
        if isinstance(cpu, dict):
            for num in range(2):
                idle = self.conn.getCPUStats(-1, 0)['idle']
                total = sum(self.conn.getCPUStats(-1, 0).values())
                diff_idle = idle - prev_idle
                diff_total = total - prev_total
                diff_usage = (1000 * (diff_total - diff_idle) / diff_total + 5) / 10
                prev_total = total
                prev_idle = idle
                if num == 0:
                    time.sleep(1)
                if diff_usage < 0:
                    diff_usage = 0
        return {'usage': round(diff_usage)}
