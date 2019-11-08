from vrtManager import util
from vrtManager.IPy import IP
from vrtManager.connection import wvmConnect
from lxml import etree
from libvirt import VIR_NETWORK_SECTION_IP_DHCP_HOST
from libvirt import VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, VIR_NETWORK_UPDATE_COMMAND_DELETE, VIR_NETWORK_UPDATE_COMMAND_MODIFY
from libvirt import VIR_NETWORK_UPDATE_AFFECT_LIVE, VIR_NETWORK_UPDATE_AFFECT_CONFIG


def network_size(subnet, dhcp=None):
    """
    Func return gateway, mask and dhcp pool.
    """
    mask = IP(subnet).strNetmask()
    addr = IP(subnet)
    gateway = addr[1].strCompressed()
    if addr.version() == 4:
        dhcp_pool = [addr[2].strCompressed(), addr[addr.len() - 2].strCompressed()]
    if addr.version() == 6:
        mask = mask.lstrip('/') if '/' in mask else mask
        dhcp_pool = [IP(addr[0].strCompressed() + hex(256)), IP(addr[0].strCompressed() + hex(512 - 1))]
    if dhcp:
        return gateway, mask, dhcp_pool
    else:
        return gateway, mask, None


class wvmNetworks(wvmConnect):

    def get_networks_info(self):
        get_networks = self.get_networks()
        networks = []
        for network in get_networks:
            net = self.get_network(network)
            net_status = net.isActive()
            net_bridge = net.bridgeName()
            net_forward = util.get_xml_path(net.XMLDesc(0), "/network/forward/@mode")
            networks.append({'name': network, 'status': net_status,
                             'device': net_bridge, 'forward': net_forward})
        return networks

    def define_network(self, xml):
        self.wvm.networkDefineXML(xml)

    def create_network(self, name, forward,
                       ipv4, gateway, mask, dhcp4,
                       ipv6, gateway6, prefix6, dhcp6,
                       bridge, openvswitch, fixed=False):
        xml = """
            <network>
                <name>%s</name>""" % name
        if forward in ['nat', 'route', 'bridge']:
            xml += """<forward mode='%s'/>""" % forward
        xml += """<bridge """
        if forward in ['nat', 'route', 'none']:
            xml += """stp='on' delay='0'"""
        if forward == 'bridge':
            xml += """name='%s'""" % bridge
        xml += """/>"""
        if openvswitch is True:
            xml += """<virtualport type='openvswitch'/>"""
        if forward != 'bridge':
            if ipv4:
                xml += """<ip address='%s' netmask='%s'>""" % (gateway, mask)
                if dhcp4:
                    xml += """<dhcp>
                                <range start='%s' end='%s' />""" % (dhcp4[0], dhcp4[1])
                    if fixed:
                        fist_oct = int(dhcp4[0].strip().split('.')[3])
                        last_oct = int(dhcp4[1].strip().split('.')[3])
                        for ip in range(fist_oct, last_oct + 1):
                            xml += """<host mac='%s' ip='%s.%s' />""" % (util.randomMAC(), gateway[:-2], ip)
                    xml += """</dhcp>"""
                xml += """</ip>"""
            if ipv6:
                xml += """<ip family='ipv6' address='%s' prefix='%s'>""" % (gateway6, prefix6)
                if dhcp6:
                    xml += """<dhcp>
                                 <range start='%s' end='%s' />""" % (dhcp6[0], dhcp6[1])
                    xml += """</dhcp>"""
                xml += """</ip>"""
        xml += """</network>"""
        self.define_network(xml)
        net = self.get_network(name)
        net.create()
        net.setAutostart(1)


class wvmNetwork(wvmConnect):
    def __init__(self, host, login, passwd, conn, net):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self.net = self.get_network(net)
        self.parent_count = len(self.get_ip_networks())

    def get_name(self):
        return self.net.name()

    def _XMLDesc(self, flags):
        return self.net.XMLDesc(flags)

    def get_autostart(self):
        return self.net.autostart()

    def set_autostart(self, value):
        self.net.setAutostart(value)

    def is_active(self):
        return self.net.isActive()

    def get_uuid(self):
        return self.net.UUIDString()

    def get_bridge_device(self):
        try:
            return self.net.bridgeName()
        except:
            return None

    def start(self):
        self.net.create()

    def stop(self):
        self.net.destroy()

    def delete(self):
        self.net.undefine()

    def update(self, command, section, xml, parentIndex, flags=0):
        return self.net.update(command, section, parentIndex, xml, flags)

    def get_ip_networks(self):
        ip_networks = dict()
        xml = self._XMLDesc(0)
        if util.get_xml_path(xml, "/network/ip") is None:
            return ip_networks
        tree = etree.fromstring(xml)
        ips = tree.findall('.ip')
        for ip in ips:
            address_str = ip.get('address')
            netmask_str = ip.get('netmask')
            prefix = ip.get('prefix')
            family = ip.get('family', 'ipv4')
            base = 32 if family == 'ipv4' else 128
            if prefix:
                prefix = int(prefix)
                binstr = ((prefix * "1") + ((base - prefix) * "0"))
                netmask_str = str(IP(int(binstr, base=2)))

            if netmask_str:
                netmask = IP(netmask_str)
                gateway = IP(address_str)
                network = IP(gateway.int() & netmask.int())
                netmask_str = netmask_str if family == 'ipv4' else str(prefix)
                ret = IP(str(network) + "/" + netmask_str)
            else:
                ret = IP(str(address_str))
            ip_networks[family] = ret
        return ip_networks

    def get_network_mac(self):
        xml = self._XMLDesc(0)
        mac = util.get_xml_path(xml, "/network/mac/@address")
        return mac

    def get_network_forward(self):
        xml = self._XMLDesc(0)
        fw = util.get_xml_path(xml, "/network/forward/@mode")
        forward_dev = util.get_xml_path(xml, "/network/forward/@dev")
        return [fw, forward_dev]

    def get_dhcp_range(self, family='ipv4'):
        xml = self._XMLDesc(0)
        if family == 'ipv4':
            dhcpstart = util.get_xml_path(xml, "/network/ip[not(@family='ipv6')]/dhcp/range[1]/@start")
            dhcpend = util.get_xml_path(xml, "/network/ip[not(@family='ipv6')]/dhcp/range[1]/@end")
        if family == 'ipv6':
            dhcpstart = util.get_xml_path(xml, "/network/ip[@family='ipv6']/dhcp/range[1]/@start")
            dhcpend = util.get_xml_path(xml, "/network/ip[@family='ipv6']/dhcp/range[1]/@end")

        if not dhcpstart or not dhcpend:
            return None

        return [IP(dhcpstart), IP(dhcpend)]

    def get_dhcp_range_start(self, family='ipv4'):
        dhcp = self.get_dhcp_range(family)
        if not dhcp:
            return None
        return dhcp[0]

    def get_dhcp_range_end(self, family='ipv4'):
        dhcp = self.get_dhcp_range(family)
        if not dhcp:
            return None
        return dhcp[1]

    def can_pxe(self):
        xml = self._XMLDesc(0)
        forward = self.get_network_forward()[0]
        if forward and forward != "nat":
            return True
        return bool(util.get_xml_path(xml, "/network/ip/dhcp/bootp/@file"))

    def get_dhcp_host_addr(self, family='ipv4'):
        result = list()
        tree = etree.fromstring(self._XMLDesc(0))

        for ipdhcp in tree.findall("./ip"):
            if family == 'ipv4':
                if ipdhcp.get('family') is None:
                    hosts = ipdhcp.findall('./dhcp/host')
                    for host in hosts:
                        ip = host.get('ip')
                        mac = host.get('mac')
                        name = host.get('name','')
                        result.append({'ip': ip, 'mac': mac, 'name': name})
                    return result
                else:
                    continue
            if family == 'ipv6':
                hosts = tree.xpath("./ip[@family='ipv6']/dhcp/host")
                for host in hosts:
                    ip = host.get('ip')
                    id = host.get('id')
                    name = host.get('name','')
                    result.append({'ip': ip, 'id': id, 'name': name})
                return result

    def modify_dhcp_range(self, range_start, range_end, family='ipv4'):
        if not self.is_active():
            tree = etree.fromstring(self._XMLDesc(0))
            if family == 'ipv4':
                range = tree.xpath("./ip[not(@family='ipv6')]/dhcp/range")
            if family == 'ipv6':
                range = tree.xpath("./ip[@family='ipv6']/dhcp/range")
            range[0].set('start', range_start)
            range[0].set('end', range_end)
            self.wvm.networkDefineXML(etree.tostring(tree))

    def delete_fixed_address(self, ip, family='ipv4'):
        tree = etree.fromstring(self._XMLDesc(0))
        if family == 'ipv4':
            hosts = tree.xpath("/network/ip[not(@family='ipv6')]/dhcp/host")
            parent_index = self.parent_count - 2
        if family == 'ipv6':
            hosts = tree.xpath("/network/ip[@family='ipv6']/dhcp/host")
            parent_index = self.parent_count - 1
        for h in hosts:
            if h.get('ip') == ip:
                if family == 'ipv4':
                    new_xml = '<host mac="{}" name="{}" ip="{}"/>'.format(h.get('mac'), h.get('name'), ip)
                if family == 'ipv6':
                    new_xml = '<host id="{}" name="{}" ip="{}"/>'.format(h.get('id'), h.get('name'), ip)

                self.update(VIR_NETWORK_UPDATE_COMMAND_DELETE, VIR_NETWORK_SECTION_IP_DHCP_HOST,
                            new_xml,
                            parent_index,
                            VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG)
                break

    def modify_fixed_address(self, name, address, mac_duid, family='ipv4'):
        tree = etree.fromstring(self._XMLDesc(0))
        if family == 'ipv4':
            new_xml = '<host mac="{}" {} ip="{}"/>'.format(mac_duid, 'name="' + name + '"' if name else '', IP(address))
            hosts = tree.xpath("./ip[not(@family='ipv6')]/dhcp/host")
            compare_var = 'mac'
            parent_index = self.parent_count - 2
        if family == 'ipv6':
            new_xml = '<host id="{}" {} ip="{}"/>'.format(mac_duid, 'name="' + name + '"' if name else '', IP(address))
            hosts = tree.xpath("./ip[@family='ipv6']/dhcp/host")
            compare_var = 'id'
            parent_index = self.parent_count - 1
        new_host_xml = etree.fromstring(new_xml)

        host = None
        for h in hosts:
            if h.get(compare_var) == mac_duid:
                host = h
                break
        if host is None:
            self.update(VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, VIR_NETWORK_SECTION_IP_DHCP_HOST, new_xml,
                        parent_index,
                        VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG)
        else:
            # change the host
            if host.get('name') == new_host_xml.get('name') and host.get('ip') == new_host_xml.get('ip'):
                return False
            else:
                self.update(VIR_NETWORK_UPDATE_COMMAND_MODIFY, VIR_NETWORK_SECTION_IP_DHCP_HOST, new_xml,
                            parent_index,
                            VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG)

