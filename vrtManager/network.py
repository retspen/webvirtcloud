from libvirt import (
    VIR_NETWORK_SECTION_IP_DHCP_HOST,
    VIR_NETWORK_UPDATE_AFFECT_CONFIG,
    VIR_NETWORK_UPDATE_AFFECT_LIVE,
    VIR_NETWORK_UPDATE_COMMAND_ADD_LAST,
    VIR_NETWORK_UPDATE_COMMAND_DELETE,
    VIR_NETWORK_UPDATE_COMMAND_MODIFY, libvirtError)
from lxml import etree
from vrtManager import util
from vrtManager.connection import wvmConnect
from vrtManager.IPy import IP


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
        mask = mask.lstrip("/") if "/" in mask else mask
        dhcp_pool = [IP(addr[0].strCompressed() + hex(256)), IP(addr[0].strCompressed() + hex(512 - 1))]

    return (gateway, mask, dhcp_pool) if dhcp else (gateway, mask, None)


class wvmNetworks(wvmConnect):
    def get_networks_info(self):
        get_networks = self.get_networks()
        networks = []
        for network in get_networks:
            net = self.get_network(network)
            net_status = net.isActive()
            try:
                net_bridge = net.bridgeName()
            except libvirtError:
                net_bridge = util.get_xml_path(net.XMLDesc(0), "/network/forward/interface/@dev")

            net_forward = util.get_xml_path(net.XMLDesc(0), "/network/forward/@mode")
            networks.append({
                "name": network, 
                "status": net_status, 
                "device": net_bridge, 
                "forward": net_forward
                })

        return networks

    def define_network(self, xml):
        self.wvm.networkDefineXML(xml)

    def create_network(
        self,
        name,
        forward,
        ipv4,
        gateway,
        mask,
        dhcp4,
        ipv6,
        gateway6,
        prefix6,
        dhcp6,
        bridge,
        openvswitch,
        fixed=False,
    ):
        xml = f"""
            <network>
                <name>{name}</name>"""
        if forward in ["nat", "route", "bridge"]:
            xml += f"""<forward mode='{forward}'/>"""
        if forward == "macvtap":
            xml += f"""<forward mode='bridge'>
                          <interface dev='{bridge}'/>
                       </forward>"""
        else:
            xml += """<bridge """
            if forward in ["nat", "route", "none"]:
                xml += """stp='on' delay='0'"""
            if forward == "bridge":
                xml += f"""name='{bridge}'"""
            xml += """/>"""
            if openvswitch is True:
                xml += """<virtualport type='openvswitch'/>"""
        if forward not in ["bridge", "macvtap"]:
            if ipv4:
                xml += f"""<ip address='{gateway}' netmask='{mask}'>"""
                if dhcp4:
                    xml += f"""<dhcp>
                                <range start='{dhcp4[0]}' end='{dhcp4[1]}' />"""
                    if fixed:
                        fist_oct = int(dhcp4[0].strip().split(".")[3])
                        last_oct = int(dhcp4[1].strip().split(".")[3])
                        for ip in range(fist_oct, last_oct + 1):
                            xml += f"""<host mac='{util.randomMAC()}' ip='{gateway[:-2]}.{ip}' />"""
                    xml += """</dhcp>"""
                xml += """</ip>"""
            if ipv6:
                xml += f"""<ip family='ipv6' address='{gateway6}' prefix='{prefix6}'>"""
                if dhcp6:
                    xml += f"""<dhcp>
                                 <range start='{dhcp6[0]}' end='{dhcp6[1]}' />"""
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
        self.leases = None
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
        except Exception:
            return util.get_xml_path(self._XMLDesc(0), "/network/forward/interface/@dev")

    def start(self):
        self.net.create()

    def stop(self):
        self.net.destroy()

    def delete(self):
        self.net.undefine()

    def update(self, command, section, xml, parentIndex, flags=0):
        return self.net.update(command, section, parentIndex, xml, flags)

    def get_ip_networks(self):
        ip_networks = {}
        xml = self._XMLDesc(0)
        if util.get_xml_path(xml, "/network/ip") is None:
            return ip_networks
        tree = etree.fromstring(xml)
        ips = tree.findall(".ip")
        for ip in ips:
            address_str = ip.get("address")
            netmask_str = ip.get("netmask")
            prefix = ip.get("prefix")
            family = ip.get("family", "ipv4")
            if prefix:
                prefix = int(prefix)
                base = 32 if family == "ipv4" else 128
                binstr = prefix * "1" + (base - prefix) * "0"
                netmask_str = str(IP(int(binstr, base=2)))

            if netmask_str:
                netmask = IP(netmask_str)
                gateway = IP(address_str)
                network = IP(gateway.int() & netmask.int())
                netmask_str = netmask_str if family == "ipv4" else str(prefix)
                ret = IP(str(network) + "/" + netmask_str)
            else:
                ret = IP(str(address_str))
            ip_networks[family] = ret
        return ip_networks

    def get_network_mac(self):
        xml = self._XMLDesc(0)
        return util.get_xml_path(xml, "/network/mac/@address")

    def get_network_forward(self):
        xml = self._XMLDesc(0)
        fw = util.get_xml_path(xml, "/network/forward/@mode")
        forward_dev = util.get_xml_path(xml, "/network/forward/@dev")
        return [fw, forward_dev]

    def get_dhcp_range(self, family="ipv4"):
        xml = self._XMLDesc(0)
        if family == "ipv4":
            dhcpstart = util.get_xml_path(xml, "/network/ip[not(@family='ipv6')]/dhcp/range[1]/@start")
            dhcpend = util.get_xml_path(xml, "/network/ip[not(@family='ipv6')]/dhcp/range[1]/@end")
        if family == "ipv6":
            dhcpstart = util.get_xml_path(xml, "/network/ip[@family='ipv6']/dhcp/range[1]/@start")
            dhcpend = util.get_xml_path(xml, "/network/ip[@family='ipv6']/dhcp/range[1]/@end")

        return None if not dhcpstart or not dhcpend else [IP(dhcpstart), IP(dhcpend)]

    def get_dhcp_range_start(self, family="ipv4"):
        dhcp = self.get_dhcp_range(family)
        return dhcp[0] if dhcp else None

    def get_dhcp_range_end(self, family="ipv4"):
        dhcp = self.get_dhcp_range(family)
        return dhcp[1] if dhcp else None

    def can_pxe(self):
        xml = self._XMLDesc(0)
        forward = self.get_network_forward()[0]
        if forward and forward != "nat":
            return True
        return bool(util.get_xml_path(xml, "/network/ip/dhcp/bootp/@file"))

    def get_dhcp_host_addr(self, family="ipv4"):
        result = []
        tree = etree.fromstring(self._XMLDesc(0))
        for ipdhcp in tree.findall("./ip"):
            if family == "ipv4":
                if ipdhcp.get("family") is not None:
                    continue
                hosts = ipdhcp.findall("./dhcp/host")
                for host in hosts:
                    host_ip = host.get("ip")
                    mac = host.get("mac")
                    name = host.get("name", "")
                    result.append({"ip": host_ip, "mac": mac, "name": name})
                return result
            if family == "ipv6":
                hosts = tree.xpath("./ip[@family='ipv6']/dhcp/host")
                for host in hosts:
                    host_ip = host.get("ip")
                    host_id = host.get("id")
                    name = host.get("name", "")
                    result.append({"ip": host_ip, "id": host_id, "name": name})
                return result

    def modify_dhcp_range(self, range_start, range_end, family="ipv4"):
        if not self.is_active():
            tree = etree.fromstring(self._XMLDesc(0))
            if family == "ipv4":
                dhcp_range = tree.xpath("./ip[not(@family='ipv6')]/dhcp/range")
            if family == "ipv6":
                dhcp_range = tree.xpath("./ip[@family='ipv6']/dhcp/range")
            dhcp_range[0].set("start", range_start)
            dhcp_range[0].set("end", range_end)
            self.wvm.networkDefineXML(etree.tostring(tree).decode())

    def delete_fixed_address(self, ip, family="ipv4"):
        tree = etree.fromstring(self._XMLDesc(0))
        if family == "ipv4":
            hosts = tree.xpath("/network/ip[not(@family='ipv6')]/dhcp/host")
            parent_index = self.parent_count - 2
        if family == "ipv6":
            hosts = tree.xpath("/network/ip[@family='ipv6']/dhcp/host")
            parent_index = self.parent_count - 1
        for h in hosts:
            if h.get("ip") == ip:
                if family == "ipv4":
                    new_xml = f'<host mac="{h.get("mac")}" name="{h.get("name")}" ip="{ip}"/>'
                if family == "ipv6":
                    new_xml = f'<host id="{h.get("id")}" name="{h.get("name")}" ip="{ip}"/>'

                self.update(
                    VIR_NETWORK_UPDATE_COMMAND_DELETE,
                    VIR_NETWORK_SECTION_IP_DHCP_HOST,
                    new_xml,
                    parent_index,
                    VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG,
                )
                break

    def modify_fixed_address(self, name, address, mac_duid, family="ipv4"):
        tree = etree.fromstring(self._XMLDesc(0))
        if family == "ipv4":
            new_xml = '<host mac="{}" {} ip="{}"/>'.format(mac_duid, 'name="' + name + '"' if name else "", IP(address))
            hosts = tree.xpath("./ip[not(@family='ipv6')]/dhcp/host")
            compare_var = "mac"
            parent_index = self.parent_count - 2
        if family == "ipv6":
            new_xml = '<host id="{}" {} ip="{}"/>'.format(mac_duid, 'name="' + name + '"' if name else "", IP(address))
            hosts = tree.xpath("./ip[@family='ipv6']/dhcp/host")
            compare_var = "id"
            parent_index = self.parent_count - 1
        new_host_xml = etree.fromstring(new_xml)
        host = next((h for h in hosts if h.get(compare_var) == mac_duid), None)
        if host is None:
            self.update(
                VIR_NETWORK_UPDATE_COMMAND_ADD_LAST,
                VIR_NETWORK_SECTION_IP_DHCP_HOST,
                new_xml,
                parent_index,
                VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG,
            )
        else:
            # change the host
            if host.get("name") == new_host_xml.get("name") and host.get("ip") == new_host_xml.get("ip"):
                return False
            else:
                self.update(
                    VIR_NETWORK_UPDATE_COMMAND_MODIFY,
                    VIR_NETWORK_SECTION_IP_DHCP_HOST,
                    new_xml,
                    parent_index,
                    VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG,
                )

    def get_qos(self):
        qos_values = {}
        tree = etree.fromstring(self._XMLDesc(0))
        qos = tree.xpath("/network/bandwidth")
        if qos:
            qos = qos[0]

            in_qos = qos.find("inbound")
            if in_qos is not None:
                in_av = in_qos.get("average")
                in_peak = in_qos.get("peak")
                in_burst = in_qos.get("burst")
                qos_values["inbound"] = {"average": in_av, "peak": in_peak, "burst": in_burst}

            out_qos = qos.find("outbound")
            if out_qos is not None:
                out_av = out_qos.get("average")
                out_peak = out_qos.get("peak")
                out_burst = out_qos.get("burst")
                qos_values["outbound"] = {"average": out_av, "peak": out_peak, "burst": out_burst}
        return qos_values

    def set_qos(self, direction, average, peak, burst):
        if direction not in ("inbound","outbound"):
            raise Exception("Direction must be inbound or outbound")

        xml = f"<{direction} average='{average}' peak='{peak}' burst='{burst}'/>"
        tree = etree.fromstring(self._XMLDesc(0))

        band = tree.xpath("/network/bandwidth")
        if len(band) == 0:
            xml = f"<bandwidth>{xml}</bandwidth>"
            tree.append(etree.fromstring(xml))
        else:
            direct = band[0].find(direction)
            if direct is not None:
                parent = direct.getparent()
                parent.remove(direct)
                parent.append(etree.fromstring(xml))
            else:
                band[0].append(etree.fromstring(xml))
        new_xml = etree.tostring(tree).decode()
        self.wvm.networkDefineXML(new_xml)

    def unset_qos(self, direction):
        tree = etree.fromstring(self._XMLDesc(0))
        for direct in tree.xpath(f"/network/bandwidth/{direction}"):
            parent = direct.getparent()
            parent.remove(direct)

        self.wvm.networkDefineXML(etree.tostring(tree).decode())

    def edit_network(self, new_xml):
        self.wvm.networkDefineXML(new_xml)

    def refresh_dhcp_leases(self):
        try:
            self.leases = self.net.DHCPLeases()
        except Exception as e:
            self.leases = []
            raise f"Error getting {self} DHCP leases: {e}" from e

    def get_dhcp_leases(self):
        if self.leases is None:
            self.refresh_dhcp_leases()
        return self.leases
