import copy
import ipaddress
from functools import cached_property

from libvirt import (
    VIR_DOMAIN_XML_INACTIVE,
    VIR_ERR_NO_DOMAIN,
    VIR_NETWORK_SECTION_IP_DHCP_HOST,
    VIR_NETWORK_UPDATE_AFFECT_CONFIG,
    VIR_NETWORK_UPDATE_AFFECT_LIVE,
    VIR_NETWORK_UPDATE_COMMAND_ADD_LAST,
    VIR_NETWORK_UPDATE_COMMAND_DELETE,
    VIR_NETWORK_XML_INACTIVE,
    libvirtError,
)
from lxml import etree
from vrtManager import util

from vrtManager.connection import wvmConnect


def network_size(subnet, dhcp=None):
    """
    Func return gateway, mask and dhcp pool.
    """
    net = ipaddress.ip_network(subnet, strict=False)
    gateway = str(net.network_address + 1)
    if net.version == 4:
        mask = str(net.netmask)
        dhcp_pool = [str(net.network_address + 2), str(net.broadcast_address - 1)]
    else:
        mask = str(net.prefixlen)
        dhcp_pool = [str(net.network_address + 256), str(net.network_address + 511)]

    return (gateway, mask, dhcp_pool) if dhcp else (gateway, mask, None)


def default_prefix(address):
    """The prefix libvirt gives an address written without one: IPv6 /64, IPv4
    its class's (A /8, B /16, C /24)."""
    address = ipaddress.ip_address(address)
    if address.version == 6:
        return 64
    first = int(address) >> 24
    return 8 if first < 128 else 16 if first < 192 else 24


def ip_networks(tree):
    """Each <ip> of a network's XML, in order: its index is libvirt's parentIndex
    for changes to it. Its family, address (the host's on the network), subnet
    (by its netmask or prefix, or libvirt's default one), whether it serves
    DHCP (a <dhcp>, with or without a range: fixed addresses alone are DHCP
    too), its first range and its fixed addresses."""
    ips = []
    for index, ip in enumerate(tree.findall("ip")):
        address = ip.get("address")
        mask = ip.get("prefix") or ip.get("netmask") or (default_prefix(address) if address else None)
        dhcp = ip.find("dhcp")
        first = dhcp.find("range") if dhcp is not None else None
        ips.append({
            "index": index,
            "family": ip.get("family", "ipv4"),
            "address": address,
            "subnet": ipaddress.ip_network(f"{address}/{mask}", strict=False) if mask else None,
            "dhcp": dhcp is not None,
            "range": (first.get("start"), first.get("end")) if first is not None else None,
            "hosts": [{"ip": host.get("ip"), "mac": host.get("mac"), "id": host.get("id"), "name": host.get("name", "")}
                      for host in (dhcp.findall("host") if dhcp is not None else [])],
        })
    return ips


def network_mode(tree):
    """What kind of network the XML defines: isolated, nat, route, open,
    bridge (a bridge of the host), macvtap (a host interface, its bridge,
    private, VEPA or passthrough mode) or hostdev (SR-IOV functions)."""
    forward = tree.find("forward")
    mode = forward.get("mode", "nat") if forward is not None else "none"
    if mode in ("private", "vepa", "passthrough") or (mode == "bridge" and tree.find("bridge") is None):
        return "macvtap"
    return "isolated" if mode == "none" else mode


class wvmNetworks(wvmConnect):
    def get_networks_info(self):
        """Each network's state, autostart, device (its bridge, or a macvtap
        network's interface), forward mode and addresses (ip_networks): its
        XML is read once."""
        networks = []
        for name in self.get_networks():
            net = self.get_network(name)
            tree = etree.fromstring(net.XMLDesc(0))
            forward = tree.find("forward")
            networks.append({
                "name": name,
                "status": net.isActive(),
                "autostart": net.autostart(),
                "device": tree.xpath("string(bridge/@name)") or tree.xpath("string(forward/interface/@dev)"),
                "forward": forward.get("mode") if forward is not None else None,
                "mode": network_mode(tree),
                "ips": ip_networks(tree),
            })
        return networks

    def get_host_interfaces(self):
        """The host's interfaces a bridge or macvtap network can use: name and
        type (bridge, ethernet, bond, vlan...), not the loopback; empty when
        the host's libvirt does not list interfaces. One listing and one XML
        read per interface."""
        try:
            ifaces = self.wvm.listAllInterfaces(0)
        except libvirtError:
            return []
        found = []
        for iface in ifaces:
            if iface.name() != "lo":
                found.append({"name": iface.name(), "type": etree.fromstring(iface.XMLDesc(0)).get("type")})
        return sorted(found, key=lambda iface: iface["name"])

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
    ):
        esc_name = util.xml_escape(str(name))
        esc_forward = util.xml_escape(str(forward)) if forward else ""
        esc_bridge = util.xml_escape(str(bridge)) if bridge else ""
        esc_gateway = util.xml_escape(str(gateway)) if gateway else ""
        esc_mask = util.xml_escape(str(mask)) if mask else ""
        esc_gateway6 = util.xml_escape(str(gateway6)) if gateway6 else ""
        esc_prefix6 = util.xml_escape(str(prefix6)) if prefix6 else ""

        xml = f"""
            <network>
                <name>{esc_name}</name>"""
        if forward in ["nat", "route", "bridge"]:
            xml += f"""<forward mode='{esc_forward}'/>"""
        if forward == "macvtap":
            xml += f"""<forward mode='bridge'>
                          <interface dev='{esc_bridge}'/>
                       </forward>"""
        else:
            xml += """<bridge """
            if forward in ["nat", "route", "none"]:
                xml += """stp='on' delay='0'"""
            if forward == "bridge":
                xml += f"""name='{esc_bridge}'"""
            xml += """/>"""
            if openvswitch is True:
                xml += """<virtualport type='openvswitch'/>"""
        if forward not in ["bridge", "macvtap"]:
            if ipv4:
                xml += f"""<ip address='{esc_gateway}' netmask='{esc_mask}'>"""
                if dhcp4:
                    dhcp4_0 = util.xml_escape(str(dhcp4[0]))
                    dhcp4_1 = util.xml_escape(str(dhcp4[1]))
                    xml += f"""<dhcp>
                                <range start='{dhcp4_0}' end='{dhcp4_1}' />
                               </dhcp>"""
                xml += """</ip>"""
            if ipv6:
                xml += f"""<ip family='ipv6' address='{esc_gateway6}' prefix='{esc_prefix6}'>"""
                if dhcp6:
                    dhcp6_0 = util.xml_escape(str(dhcp6[0]))
                    dhcp6_1 = util.xml_escape(str(dhcp6[1]))
                    xml += f"""<dhcp>
                                 <range start='{dhcp6_0}' end='{dhcp6_1}' />"""
                    xml += """</dhcp>"""
                xml += """</ip>"""
        xml += """</network>"""
        net = self.wvm.networkDefineXML(xml)
        try:
            net.create()
        except libvirtError:  # e.g. the subnet is in use: the name stays free for another try
            net.undefine()
            raise
        net.setAutostart(1)


class wvmNetwork(wvmConnect):
    """A network of the host. A page reads its running definition (tree) and
    its saved one (saved) once each; a change starts from the saved
    definition read anew (config), so that two changes in a row do not undo
    each other, and forgets what the page read."""

    def __init__(self, host, login, passwd, conn, net):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self.net = self.get_network(net)

    @cached_property
    def tree(self):
        return etree.fromstring(self.net.XMLDesc(0))

    @cached_property
    def saved_xml(self):
        """The saved definition, the one the XML editor changes."""
        return self.net.XMLDesc(VIR_NETWORK_XML_INACTIVE)

    def config(self):
        return etree.fromstring(self.net.XMLDesc(VIR_NETWORK_XML_INACTIVE))

    def _forget(self):
        for read in ("tree", "saved_xml"):
            self.__dict__.pop(read, None)

    def _define(self, tree):
        self.wvm.networkDefineXML(etree.tostring(tree).decode())
        self._forget()

    def get_name(self):
        return self.net.name()

    def get_autostart(self):
        return self.net.autostart()

    def set_autostart(self, value):
        self.net.setAutostart(value)

    def is_active(self):
        return self.net.isActive()

    def get_bridge_device(self):
        """Its bridge, or a macvtap network's interface."""
        return self.tree.xpath("string(bridge/@name)") or self.tree.xpath("string(forward/interface/@dev)")

    def start(self):
        self.net.create()

    def get_mode(self):
        return network_mode(self.tree)

    def get_vms(self):
        """The VMs whose definition names this network, by name, and whether
        each is running on it now: one listing, and one XML read per stopped
        VM, two per running one (its running and its saved definition)."""
        name = self.net.name()

        def on_it(xml):
            return etree.fromstring(xml).xpath("devices/interface[@type='network']/source[@network=$name]", name=name)

        vms = []
        for dom in self.wvm.listAllDomains():
            try:
                connected = dom.isActive() and bool(on_it(dom.XMLDesc(0)))
                if connected or on_it(dom.XMLDesc(VIR_DOMAIN_XML_INACTIVE)):
                    vms.append({"name": dom.name(), "connected": connected})
            except libvirtError as err:  # a VM undefined meanwhile is not on it
                if err.get_error_code() != VIR_ERR_NO_DOMAIN:
                    raise
        return sorted(vms, key=lambda vm: vm["name"])

    def _vms_on_it(self, running_only):
        name = self.net.name()
        return self.domains_using(
            lambda domain: domain.xpath("devices/interface[@type='network']/source[@network=$name]", name=name),
            running_only,
        )

    def stop(self):
        """Refused while a running VM is on it: that VM would be cut off."""
        if vms := self._vms_on_it(running_only=True):
            raise util.OperationError(f"Network {self.net.name()} is in use by the running VMs {', '.join(vms)}; "
                                      "shut them down or remove their network cards first")
        self.net.destroy()

    def delete(self):
        """Refused while a VM's definition names it: that VM would no longer start."""
        if vms := self._vms_on_it(running_only=False):
            raise util.OperationError(f"VMs {', '.join(vms)} use network {self.net.name()} and would no longer "
                                      "start; remove their network cards first")
        self.net.undefine()

    def update(self, command, section, xml, parentIndex):
        """Changes the network's configuration and, while it runs, the running
        network too (libvirt refuses a live change on a stopped one)."""
        active = self.is_active()
        if active and self._addresses(self.tree) != self._addresses(self.config()):
            # parentIndex names the same <ip> in both only when they list the same addresses
            raise util.OperationError(f"Network {self.net.name()} runs with other addresses than it has saved; "
                                      "stop and start it first")
        flags = VIR_NETWORK_UPDATE_AFFECT_CONFIG | (VIR_NETWORK_UPDATE_AFFECT_LIVE if active else 0)
        self.net.update(command, section, parentIndex, xml, flags)
        self._forget()

    @staticmethod
    def _addresses(tree):
        return [(ip.get("family", "ipv4"), ip.get("address")) for ip in tree.findall("ip")]

    def get_ip_networks(self):
        return ip_networks(self.tree)

    def get_network_mac(self):
        return self.tree.xpath("string(mac/@address)")

    def get_network_forward(self):
        """Its forward mode (None: isolated) and the device it forwards through."""
        forward = self.tree.find("forward")
        return [forward.get("mode"), forward.get("dev")] if forward is not None else [None, None]

    def _ip(self, index):
        """The saved <ip> of that index, and what ip_networks tells of it."""
        tree = self.config()
        ips = tree.findall("ip")
        if not 0 <= index < len(ips):
            raise util.OperationError(f"Network {self.net.name()} has no such address")
        return tree, ips[index], ip_networks(tree)[index]

    def _checked_address(self, ip, address, what):
        """address as an address of the <ip> ip (ip_networks): of its family and
        subnet, and not the host's own."""
        try:
            address = ipaddress.ip_address(address)
        except ValueError:
            raise util.OperationError(f"{address} is not an IP address") from None
        if ip["subnet"] is None or address not in ip["subnet"]:
            raise util.OperationError(f"The {what} {address} is not in {ip['subnet'] or 'the network'}")
        if address == ipaddress.ip_address(ip["address"]):
            raise util.OperationError(f"{address} is the host's own address on the network")
        return address

    def modify_dhcp_range(self, index, range_start, range_end):
        """Refused while the network runs: the running network would keep the old range."""
        if self.is_active():
            raise util.OperationError(f"Stop network {self.net.name()} to change its DHCP range")
        tree, ip, info = self._ip(index)
        dhcp_range = ip.find("dhcp/range")
        if dhcp_range is None:
            raise util.OperationError(f"This address of network {self.net.name()} has no DHCP range")
        start = self._checked_address(info, range_start, "range start")
        end = self._checked_address(info, range_end, "range end")
        if start > end:
            raise util.OperationError(f"The range starts at {start}, after its end {end}")
        if start <= ipaddress.ip_address(info["address"]) <= end:
            raise util.OperationError(f"The range takes in {info['address']}, the host's own address")
        dhcp_range.set("start", str(start))
        dhcp_range.set("end", str(end))
        self._define(tree)

    def delete_fixed_address(self, index, address):
        _tree, ip, _info = self._ip(index)
        host = next((h for h in ip.findall("dhcp/host") if h.get("ip") == address), None)
        if host is None:
            raise util.OperationError(f"Network {self.net.name()} has no fixed address {address}")
        # the host as it is: a host may have only a name and an address
        self.update(VIR_NETWORK_UPDATE_COMMAND_DELETE, VIR_NETWORK_SECTION_IP_DHCP_HOST,
                    etree.tostring(host, with_tail=False).decode(), index)

    def modify_fixed_address(self, index, original, name, address, mac_duid):
        """Adds a fixed address, or changes the one that had the address
        original, keeping what the page does not show of it (a client id, a
        lease time). The address must be of the subnet, not the host's, and
        neither it, the MAC (IPv4) or DUID (IPv6) nor the name another entry's.
        A change deletes the entry and adds it anew, put back if that fails:
        libvirt's own change finds an entry by any of its MAC, address or name,
        another entry's too, and an IPv6 one never by its DUID. Returns False
        when nothing changes."""
        _tree, ip, info = self._ip(index)
        address = self._checked_address(info, address, "fixed address")
        key = "mac" if info["family"] == "ipv4" else "id"
        hosts = ip.findall("dhcp/host")
        old = None
        if original:
            old = next((h for h in hosts if h.get("ip") == original), None)
            if old is None:
                raise util.OperationError(f"The fixed address {original} is gone meanwhile; reload the page")
        for other in hosts:
            if other is old:
                continue
            if other.get("ip") == str(address):
                raise util.OperationError(f"{address} is another entry's fixed address")
            if mac_duid and other.get(key, "").lower() == mac_duid.lower():
                raise util.OperationError(f"{mac_duid} has another fixed address, {other.get('ip')}")
            if name and other.get("name") == name:
                raise util.OperationError(f"The name {name} has another fixed address, {other.get('ip')}")
        new = copy.deepcopy(old) if old is not None else etree.Element("host")
        new.tail = None
        for attribute, value in ((key, mac_duid), ("name", name), ("ip", str(address))):
            if value:
                new.set(attribute, value)
            elif attribute in new.attrib:
                del new.attrib[attribute]
        new_xml = etree.tostring(new).decode()
        if old is None:
            self.update(VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, VIR_NETWORK_SECTION_IP_DHCP_HOST, new_xml, index)
            return True
        old_xml = etree.tostring(old, with_tail=False).decode()
        if new_xml == old_xml:
            return False
        self.update(VIR_NETWORK_UPDATE_COMMAND_DELETE, VIR_NETWORK_SECTION_IP_DHCP_HOST, old_xml, index)
        try:
            self.update(VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, VIR_NETWORK_SECTION_IP_DHCP_HOST, new_xml, index)
        except libvirtError:
            self.update(VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, VIR_NETWORK_SECTION_IP_DHCP_HOST, old_xml, index)
            raise
        return True

    def get_qos(self):
        """The saved bandwidth limits: a running network takes them when it is started again."""
        qos_values = {}
        saved = etree.fromstring(self.saved_xml)
        for direction in ("inbound", "outbound"):
            limit = saved.find(f"bandwidth/{direction}")
            if limit is not None:
                qos_values[direction] = {"average": limit.get("average"), "peak": limit.get("peak"),
                                         "burst": limit.get("burst")}
        return qos_values

    def set_qos(self, direction, average, peak, burst):
        if direction not in ("inbound", "outbound"):
            raise ValueError("Direction must be inbound or outbound")
        try:
            average, peak, burst = int(average), int(peak), int(burst)
        except ValueError:
            raise ValueError("QoS rates must be whole numbers")
        tree = self.config()
        band = tree.find("bandwidth")
        if band is None:
            band = etree.SubElement(tree, "bandwidth")
        for old in band.findall(direction):
            band.remove(old)
        etree.SubElement(band, direction, average=str(average), peak=str(peak), burst=str(burst))
        self._define(tree)

    def unset_qos(self, direction):
        if direction not in ("inbound", "outbound"):
            raise ValueError("Direction must be inbound or outbound")
        tree = self.config()
        for limit in tree.findall(f"bandwidth/{direction}"):
            limit.getparent().remove(limit)
        self._define(tree)

    def edit_network(self, new_xml):
        """Defines this network anew from new_xml: of the same name and, if it
        names one, the same UUID, not another network."""
        # read for its name and UUID only, its entities not expanded: libvirt gets the text itself
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        try:
            tree = etree.fromstring(new_xml.encode(), parser)  # bytes: the XML may declare its encoding
        except etree.XMLSyntaxError as err:
            raise util.OperationError(f"The XML is not valid: {err}") from None
        if tree.tag != "network" or tree.findtext("name") != self.net.name():
            raise util.OperationError(f"The XML must define network {self.net.name()}")
        if tree.findtext("uuid") not in (None, self.net.UUIDString()):
            raise util.OperationError("The XML must keep the network's UUID")
        self.wvm.networkDefineXML(new_xml)
        self._forget()
