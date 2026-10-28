import contextlib
from functools import cached_property
from xml.etree import ElementTree

from libvirt import (
    VIR_CONNECT_LIST_DOMAINS_ACTIVE,
    VIR_ERR_NO_DOMAIN,
    VIR_ERR_NO_INTERFACE,
    VIR_ERR_XML_ERROR,
    VIR_INTERFACE_XML_INACTIVE,
    libvirtError,
)

from vrtManager import util
from vrtManager.connection import wvmConnect

# a link speed the kernel gives when it does not know one
UNKNOWN_SPEEDS = ("0", "4294967295", "-1")


@contextlib.contextmanager
def changes(conn):
    """The host's interface configuration changed as one: what fails in the
    block, or its commit, is rolled back (libvirt's interface change
    transaction). A rollback that fails too is told with the failure."""
    conn.changeBegin(0)
    try:
        yield
        conn.changeCommit(0)
    except BaseException as err:
        try:
            conn.changeRollback(0)
        except libvirtError as rollback_err:
            raise util.OperationError(f"{err}; rolling the change back failed too, "
                                      f"the host's configuration may be changed: {rollback_err}") from err
        raise


def running_xml(iface):
    """The interface's running XML, or its saved one when libvirt cannot give
    that: netcf writes a link speed of -1 for a device that has none (a
    virtio card), then refuses its own XML."""
    try:
        return iface.XMLDesc(0)
    except libvirtError as err:
        if err.get_error_code() != VIR_ERR_XML_ERROR:
            raise
        return iface.XMLDesc(VIR_INTERFACE_XML_INACTIVE)


def link_of(element):
    """An interface's or member's link state and speed in Mb/s, as libvirt
    reports them: None for what it does not."""
    link = element.find("link")
    if link is None:
        return None, None
    speed = link.get("speed")
    return link.get("state"), None if speed in (None, *UNKNOWN_SPEEDS) else speed


def attribute(element, path, name):
    """The attribute name of the child at path, or None."""
    child = element.find(path)
    return child.get(name) if child is not None else None


def interface_info(iface, tree):
    """What an interface (its libvirt object, which holds its name and MAC)
    and its XML tell: type, MAC, MTU, link state and speed, the members of a
    bridge or bond, or a VLAN's device, as reported, and a bridge's STP."""
    state, speed = link_of(tree)
    members = []
    for member in tree.findall("bridge/interface") + tree.findall("bond/interface") + tree.findall("vlan/interface"):
        member_state, member_speed = link_of(member)
        members.append({"name": member.get("name"), "type": member.get("type"), "mac": attribute(member, "mac", "address"),
                        "link": member_state, "speed": member_speed})
    return {"name": iface.name(), "type": tree.get("type"), "mac": iface.MACString() or None,
            "mtu": attribute(tree, "mtu", "size"), "link": state, "speed": speed, "members": members,
            "stp": attribute(tree, "bridge", "stp")}


def networks_by_device(conn):
    """The host's libvirt networks by the devices they use: their bridge, or
    every interface or physical function they forward to. One listing, one
    XML read per network."""
    by_device = {}
    for net in conn.listAllNetworks(0):
        tree = ElementTree.fromstring(net.XMLDesc(0))
        devices = {attribute(tree, "bridge", "name")}
        for forward in tree.findall("forward/interface") + tree.findall("forward/pf"):
            devices.add(forward.get("dev"))
        devices.discard(None)
        for device in devices:
            by_device.setdefault(device, []).append(net.name())
    return by_device


class wvmInterfaces(wvmConnect):
    def get_ifaces_info(self):
        """Every interface of the host (interface_info) and whether libvirt
        has it active: one listing, two calls per interface."""
        ifaces = []
        for iface in self.wvm.listAllInterfaces(0):
            info = interface_info(iface, ElementTree.fromstring(running_xml(iface)))
            info["state"] = iface.isActive()
            ifaces.append(info)
        return sorted(ifaces, key=lambda iface: iface["name"])

    def get_member_candidates(self, netdevs):
        """The devices of netdevs a new bridge can take: not the loopback, a
        bridge, bond or VLAN of the host nor a device in one as configured, at
        any depth (a bridge's bond's devices), not the bridge of a libvirt
        network and not a VM's tap (libvirt names them vnetN and macvtapN)."""
        taken = {"lo"}
        for iface in self.wvm.listAllInterfaces(0):
            tree = ElementTree.fromstring(iface.XMLDesc(VIR_INTERFACE_XML_INACTIVE))
            if tree.get("type") in ("bridge", "bond", "vlan"):
                taken.update(element.get("name") for element in tree.iter("interface"))
        for net in self.wvm.listAllNetworks(0):
            taken.add(util.get_xml_path(net.XMLDesc(0), "/network/bridge/@name"))
        return [dev for dev in netdevs if dev not in taken and not dev.startswith(("vnet", "macvtap"))]

    def define_iface(self, xml, flag=0):
        return self.wvm.interfaceDefineXML(xml, flag)

    def bridge_member_xml(self, netdev):
        """netdev as a bridge member: as the host defines it (a bond keeps its
        mode and devices, a vlan its tag), without what only a top-level
        interface has. A device the host does not define is ethernet."""
        try:
            member = ElementTree.fromstring(self.get_iface(netdev).XMLDesc(VIR_INTERFACE_XML_INACTIVE))
        except libvirtError as err:
            if err.get_error_code() != VIR_ERR_NO_INTERFACE:
                raise
            return f"<interface type='ethernet' name='{netdev}'/>"
        for tag in ("start", "mtu", "protocol"):
            for child in member.findall(tag):
                member.remove(child)
        return ElementTree.tostring(member, encoding="unicode")

    def create_iface(
        self,
        name,
        itype,
        mode,
        netdev,
        ipv4_type,
        ipv4_addr,
        ipv4_gw,
        ipv6_type,
        ipv6_addr,
        ipv6_gw,
        stp,
        delay,
    ):
        xml = f"""<interface type='{itype}' name='{name}'>
                    <start mode='{mode}'/>"""
        if ipv4_type == "dhcp":
            xml += """<protocol family='ipv4'>
                        <dhcp/>
                      </protocol>"""
        if ipv4_type == "static":
            address, prefix = ipv4_addr.split("/")
            xml += f"""<protocol family='ipv4'>
                        <ip address='{address}' prefix='{prefix}'/>"""
            if ipv4_gw:
                xml += f"""<route gateway='{ipv4_gw}'/>"""
            xml += """</protocol>"""
        if ipv6_type == "dhcp":
            xml += """<protocol family='ipv6'>
                        <dhcp/>
                      </protocol>"""
        if ipv6_type == "static":
            address, prefix = ipv6_addr.split("/")
            xml += f"""<protocol family='ipv6'>
                        <ip address='{address}' prefix='{prefix}'/>"""
            if ipv6_gw:
                xml += f"""<route gateway='{ipv6_gw}'/>"""
            xml += """</protocol>"""
        if itype == "bridge":
            xml += f"""<bridge stp='{stp}' delay='{delay}'>
                        {self.bridge_member_xml(netdev)}
                      </bridge>"""
        xml += """</interface>"""
        # the form refuses a name the host defines, so nothing is replaced;
        # one that does not start leaves the host as it was, its member's
        # own configuration too
        with changes(self.wvm):
            self.define_iface(xml).create()


class wvmInterface(wvmConnect):
    """An interface of the host. A page reads its running definition (tree)
    and its saved one (saved) once each."""

    def __init__(self, host, login, passwd, conn, iface):
        wvmConnect.__init__(self, host, login, passwd, conn)
        self.iface = self.get_iface(iface)

    @cached_property
    def tree(self):
        return ElementTree.fromstring(running_xml(self.iface))

    @cached_property
    def saved(self):
        """The saved definition: its start mode and addressing."""
        return ElementTree.fromstring(self.iface.XMLDesc(VIR_INTERFACE_XML_INACTIVE))

    def is_active(self):
        return self.iface.isActive()

    def get_type(self):
        return self.tree.get("type")

    def get_info(self):
        """interface_info, with its start mode and, per family, how it is
        addressed (dhcp, autoconf, static or None) and its addresses."""
        info = interface_info(self.iface, self.tree)
        info["start_mode"] = attribute(self.saved, "start", "mode")
        for family in ("ipv4", "ipv6"):
            config = self.saved.find(f"protocol[@family='{family}']")
            if config is None:
                method = None
            elif config.find("dhcp") is not None:
                method = "dhcp"
            elif config.find("autoconf") is not None:
                method = "autoconf"
            else:
                method = "static"
            # the prefix is optional in libvirt's XML
            addresses = [ip.get("address") + (f"/{ip.get('prefix')}" if ip.get("prefix") else "")
                         for ip in self.tree.findall(f"protocol[@family='{family}']/ip")]
            info[family] = {"method": method, "addresses": addresses}
        return info

    def get_vms(self, networks=()):
        """The running VMs' network cards on this bridge, directly or through
        the libvirt networks of networks (which use it): VM, tap device and
        the VM's MAC. One listing, one XML read per running VM."""
        name = self.iface.name()
        cards = []
        for dom in self.wvm.listAllDomains(VIR_CONNECT_LIST_DOMAINS_ACTIVE):
            try:
                tree = ElementTree.fromstring(dom.XMLDesc(0))
            except libvirtError as err:  # a VM stopped or undefined meanwhile is not on it
                if err.get_error_code() != VIR_ERR_NO_DOMAIN:
                    raise
                continue
            for card in tree.findall("devices/interface"):
                source = card.find("source")
                if source is not None and (source.get("bridge") == name or source.get("network") in networks):
                    cards.append({"vm": dom.name(), "tap": attribute(card, "target", "dev"), "mac": attribute(card, "mac", "address")})
        return sorted(cards, key=lambda card: (card["vm"], card["tap"] or ""))

    def stop_iface(self):
        self.iface.destroy()

    def start_iface(self):
        self.iface.create()

    def delete_iface(self):
        """Undefine the interface, stopped first. netcf removes a bridge's
        members with it, so each member is defined again on its own, as virsh
        iface-unbridge does: with the bridge's start mode and, when it is the
        only one, addresses; a bridge with addresses and several members is
        refused, which of them takes the addresses being the user's choice.
        All of it is one change of the host's configuration."""
        if self.iface.isActive():
            raise util.OperationError(f"Stop interface {self.iface.name()} before deleting it")
        tree = ElementTree.fromstring(self.iface.XMLDesc(VIR_INTERFACE_XML_INACTIVE))
        members = tree.findall("bridge/interface")
        if len(members) > 1 and tree.findall("protocol"):
            raise util.OperationError(f"Bridge {self.iface.name()} has addresses and several members: "
                                      "give the addresses to one of them on the host first")
        with changes(self.wvm):
            self.iface.undefine()
            for member in members:
                member.extend(tree.findall("start") + tree.findall("protocol"))
                self.wvm.interfaceDefineXML(ElementTree.tostring(member, encoding="unicode"), 0)
