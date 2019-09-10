from vrtManager import util
from vrtManager.IPy import IP
from vrtManager.connection import wvmConnect
from xml.etree import ElementTree
from libvirt import VIR_NETWORK_SECTION_IP_DHCP_HOST
from libvirt import VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, VIR_NETWORK_UPDATE_COMMAND_DELETE, VIR_NETWORK_UPDATE_COMMAND_MODIFY
from libvirt import VIR_NETWORK_UPDATE_AFFECT_LIVE, VIR_NETWORK_UPDATE_AFFECT_CONFIG


def network_size(net, dhcp=None):
    """
    Func return gateway, mask and dhcp pool.
    """
    mask = IP(net).strNetmask()
    addr = IP(net)
    gateway = addr[1].strNormal()
    dhcp_pool = [addr[2].strNormal(), addr[addr.len() - 2].strNormal()]
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
            net_forwd = util.get_xml_path(net.XMLDesc(0), "/network/forward/@mode")
            networks.append({'name': network, 'status': net_status,
                             'device': net_bridge, 'forward': net_forwd})
        return networks

    def define_network(self, xml):
        self.wvm.networkDefineXML(xml)

    def create_network(self, name, forward, gateway, mask, dhcp, bridge, openvswitch, fixed=False):
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
            xml += """
                        <ip address='%s' netmask='%s'>""" % (gateway, mask)
            if dhcp:
                xml += """<dhcp>
                            <range start='%s' end='%s' />""" % (dhcp[0], dhcp[1])
                if fixed:
                    fist_oct = int(dhcp[0].strip().split('.')[3])
                    last_oct = int(dhcp[1].strip().split('.')[3])
                    for ip in range(fist_oct, last_oct + 1):
                        xml += """<host mac='%s' ip='%s.%s' />""" % (util.randomMAC(), gateway[:-2], ip)
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

    def update(self, command, section, parentIndex, xml, flags=0):
        return self.net.update(command, section, parentIndex, xml, flags)

    def get_ipv4_network(self):
        xml = self._XMLDesc(0)
        if util.get_xml_path(xml, "/network/ip") is None:
            return None
        addrStr = util.get_xml_path(xml, "/network/ip/@address")
        netmaskStr = util.get_xml_path(xml, "/network/ip/@netmask")
        prefix = util.get_xml_path(xml, "/network/ip/@prefix")

        if prefix:
            prefix = int(prefix)
            binstr = ((prefix * "1") + ((32 - prefix) * "0"))
            netmaskStr = str(IP(int(binstr, base=2)))

        if netmaskStr:
            netmask = IP(netmaskStr)
            gateway = IP(addrStr)
            network = IP(gateway.int() & netmask.int())
            ret = IP(str(network) + "/" + netmaskStr)
        else:
            ret = IP(str(addrStr))

        return ret

    def get_ipv4_forward(self):
        xml = self._XMLDesc(0)
        fw = util.get_xml_path(xml, "/network/forward/@mode")
        forwardDev = util.get_xml_path(xml, "/network/forward/@dev")
        return [fw, forwardDev]

    def get_ipv4_dhcp_range(self):
        xml = self._XMLDesc(0)
        dhcpstart = util.get_xml_path(xml, "/network/ip/dhcp/range[1]/@start")
        dhcpend = util.get_xml_path(xml, "/network/ip/dhcp/range[1]/@end")
        if not dhcpstart or not dhcpend:
            return None

        return [IP(dhcpstart), IP(dhcpend)]

    def get_ipv4_dhcp_range_start(self):
        dhcp = self.get_ipv4_dhcp_range()
        if not dhcp:
            return None

        return dhcp[0]

    def get_ipv4_dhcp_range_end(self):
        dhcp = self.get_ipv4_dhcp_range()
        if not dhcp:
            return None

        return dhcp[1]

    def can_pxe(self):
        xml = self._XMLDesc(0)
        forward = self.get_ipv4_forward()[0]
        if forward and forward != "nat":
            return True
        return bool(util.get_xml_path(xml, "/network/ip/dhcp/bootp/@file"))

    def get_mac_ipaddr(self):
        def network(doc):
            result = []
            for net in doc.xpath('/network/ip/dhcp/host'):
                ip = net.xpath('@ip')[0]
                mac = net.xpath('@mac')[0]
                name = net.xpath('@name')
                name = name[0] if name else ""

                result.append({'ip': ip, 'mac': mac, 'name': name})
            return result

        return util.get_xml_path(self._XMLDesc(0), func=network)
    
    def modify_fixed_address(self, name, address, mac):
        util.validate_macaddr(mac)
        if name:
            new_xml = '<host mac="{}" name="{}" ip="{}"/>'.format(mac, name, IP(address))
        else:
            new_xml = '<host mac="{}" ip="{}"/>'.format(mac, IP(address))
        new_host_xml = ElementTree.fromstring(new_xml)

        tree = ElementTree.fromstring(self._XMLDesc(0))
        hosts = tree.findall("./ip/dhcp/host")

        host = None
        for h in hosts:
            if h.get('mac') == mac:
                host = h
                break
        if host is None:
            self.update(VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, VIR_NETWORK_SECTION_IP_DHCP_HOST, -1, new_xml,
                        VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG)
        else:
            # change the host
            if host.get('name') == new_host_xml.get('name') and host.get('ip') == new_host_xml.get('ip'):
                return False
            else:
                self.update(VIR_NETWORK_UPDATE_COMMAND_MODIFY, VIR_NETWORK_SECTION_IP_DHCP_HOST, -1, new_xml,
                            VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG)

    def delete_fixed_address(self, mac):
        util.validate_macaddr(mac)
        tree = ElementTree.fromstring(self._XMLDesc(0))
        hosts = tree.findall("./ip/dhcp/host")

        for h in hosts:
            if h.get('mac') == mac:
                new_xml = '<host mac="{}" name="{}" ip="{}"/>'.format(mac, h.get('name'), h.get('ip'))
                self.update(VIR_NETWORK_UPDATE_COMMAND_DELETE, VIR_NETWORK_SECTION_IP_DHCP_HOST, -1, new_xml,
                            VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG)
                break

    def modify_dhcp_range(self, range_start, range_end):
        if not self.is_active():
            new_range = '<range start="{}" end="{}"/>'.format(range_start, range_end)
            tree = ElementTree.fromstring(self._XMLDesc(0))
            dhcp = tree.find("./ip/dhcp")
            old_range = dhcp.find('range')
            dhcp.remove(old_range)
            dhcp.append(ElementTree.fromstring(new_range))

            self.wvm.networkDefineXML(ElementTree.tostring(tree))
