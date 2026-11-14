"""The interface XML wvmInterfaces writes from the form's values: IPv4,
IPv6 and a bridge's member."""

from unittest.mock import MagicMock

import libvirt
from django.test import SimpleTestCase
from lxml import etree

from vrtManager.interface import wvmInterfaces


class Ipv6XmlTestCase(SimpleTestCase):
    def xml(self, gw):
        conn = wvmInterfaces.__new__(wvmInterfaces)
        conn.host = "192.0.2.1"
        conn.wvm = MagicMock()
        conn.define_iface = MagicMock()
        conn.get_iface = MagicMock()
        conn.get_iface.return_value.XMLDesc.return_value = "<interface type='ethernet' name='eth1'/>"
        conn.create_iface("br1", "bridge", "onboot", "eth1", "none", "", "", "static", "2001:db8::10/64", gw, "on", 0)
        return etree.fromstring(conn.define_iface.call_args[0][0])

    def test_static_address_with_gateway(self):
        proto = self.xml("2001:db8::1").find("protocol[@family='ipv6']")
        self.assertEqual(proto.find("ip").attrib, {"address": "2001:db8::10", "prefix": "64"})
        self.assertEqual(proto.find("route").get("gateway"), "2001:db8::1")

    def test_no_empty_route_without_gateway(self):
        self.assertIsNone(self.xml("").find("protocol[@family='ipv6']/route"))


class Ipv4XmlTestCase(SimpleTestCase):
    def xml(self, addr, gw):
        conn = wvmInterfaces.__new__(wvmInterfaces)
        conn.host = "192.0.2.1"
        conn.wvm = MagicMock()
        conn.define_iface = MagicMock()
        conn.get_iface = MagicMock()
        conn.get_iface.return_value.XMLDesc.return_value = "<interface type='ethernet' name='eth1'/>"
        conn.create_iface("br1", "bridge", "onboot", "eth1", "static", addr, gw, "none", "", "", "on", 0)
        return etree.fromstring(conn.define_iface.call_args[0][0])

    def test_static_address_with_gateway(self):
        proto = self.xml("192.0.2.10/24", "192.0.2.1").find("protocol[@family='ipv4']")
        self.assertEqual(proto.find("ip").attrib, {"address": "192.0.2.10", "prefix": "24"})
        self.assertEqual(proto.find("route").get("gateway"), "192.0.2.1")

    def test_no_empty_route_without_gateway(self):
        self.assertIsNone(self.xml("192.0.2.10/24", "").find("protocol[@family='ipv4']/route"))


def no_interface(name):
    err = libvirt.libvirtError("Interface not found: no interface with matching name '%s'" % name)
    err.err = (libvirt.VIR_ERR_NO_INTERFACE, libvirt.VIR_FROM_INTERFACE, str(err), 2, name, None, None, 0, 0)
    return err


class BridgeMemberXmlTestCase(SimpleTestCase):
    """A bridge member is declared as the host defines it: a bond keeps its
    mode and devices, a vlan its tag and device."""

    def member(self, host_xml):
        conn = wvmInterfaces.__new__(wvmInterfaces)
        conn.host = "192.0.2.1"
        conn.wvm = MagicMock()
        conn.define_iface = MagicMock()

        def get_iface(name):
            if host_xml is None:
                raise no_interface(name)
            iface = MagicMock()
            iface.XMLDesc.return_value = host_xml
            return iface

        conn.get_iface = MagicMock(side_effect=get_iface)
        conn.create_iface("br1", "bridge", "onboot", "bond0", "none", "", "", "none", "", "", "on", 0)
        self.conn = conn
        self.assertTrue(conn.define_iface.return_value.create.called)
        members = etree.fromstring(conn.define_iface.call_args[0][0]).findall("bridge/interface")
        self.assertEqual(len(members), 1)
        return members[0]

    def test_a_bond_keeps_its_mode_and_devices(self):
        member = self.member(
            "<interface type='bond' name='bond0'><start mode='onboot'/><mtu size='9000'/>"
            "<protocol family='ipv4'><dhcp/></protocol>"
            "<bond mode='active-backup'><miimon freq='100'/>"
            "<interface type='ethernet' name='eth0'><mac address='52:54:00:00:00:01'/></interface>"
            "<interface type='ethernet' name='eth1'/></bond></interface>"
        )
        self.assertEqual((member.get("type"), member.get("name")), ("bond", "bond0"))
        self.assertEqual(member.find("bond").get("mode"), "active-backup")
        self.assertEqual([i.get("name") for i in member.findall("bond/interface")], ["eth0", "eth1"])
        self.assertEqual(member.find("bond/miimon").get("freq"), "100")
        # what only a top-level interface has: the bridge holds the addresses
        for tag in ("start", "mtu", "protocol"):
            self.assertIsNone(member.find(tag), tag)
        # the bridge takes its MTU: netcf gives it to the members, jumbo frames go on
        bridge = etree.fromstring(self.conn.define_iface.call_args[0][0])
        self.assertEqual(bridge.xpath("mtu/@size"), ["9000"])

    def test_a_vlan_keeps_its_tag_and_device(self):
        member = self.member(
            "<interface type='vlan' name='bond0'><start mode='onboot'/>"
            "<vlan tag='42'><interface name='eth0'/></vlan></interface>"
        )
        self.assertEqual(member.get("type"), "vlan")
        self.assertEqual(member.find("vlan").get("tag"), "42")
        self.assertEqual(member.find("vlan/interface").get("name"), "eth0")
        self.assertIsNone(member.find("start"))

    def test_a_device_the_host_does_not_define_is_ethernet(self):
        member = self.member(None)
        self.assertEqual(member.attrib, {"type": "ethernet", "name": "bond0"})
        self.assertEqual(etree.fromstring(self.conn.define_iface.call_args[0][0]).xpath("mtu"), [])

    def test_other_lookup_errors_are_not_hidden(self):
        conn = wvmInterfaces.__new__(wvmInterfaces)
        conn.host = "192.0.2.1"
        conn.wvm = MagicMock()
        conn.define_iface = MagicMock()
        err = libvirt.libvirtError("cannot recv data")
        err.err = (libvirt.VIR_ERR_SYSTEM_ERROR, libvirt.VIR_FROM_RPC, str(err), 2, None, None, None, 0, 0)
        conn.get_iface = MagicMock(side_effect=err)
        with self.assertRaises(libvirt.libvirtError):
            conn.create_iface("br1", "bridge", "onboot", "bond0", "none", "", "", "none", "", "", "on", 0)
        self.assertFalse(conn.define_iface.called)

    def test_an_interface_that_does_not_start_is_rolled_back(self):
        # the definition, and the member's own configuration it changed, as they were
        conn = wvmInterfaces.__new__(wvmInterfaces)
        conn.host = "192.0.2.1"
        conn.wvm = MagicMock()
        conn.define_iface = MagicMock()
        iface = conn.define_iface.return_value
        iface.create.side_effect = libvirt.libvirtError("failed to bring up br1")
        with self.assertRaises(libvirt.libvirtError):
            conn.create_iface("br1", "ethernet", "onboot", "", "none", "", "", "none", "", "", "on", 0)
        conn.wvm.changeRollback.assert_called_once_with(0)
        conn.wvm.changeCommit.assert_not_called()


class PanelDeviceTestCase(SimpleTestCase):
    """The interface that carries the address the panel reaches the host by,
    and the devices in it, keep the panel's way to the host."""

    def conn(self, cls):
        conn = cls.__new__(cls)
        conn.host = "192.0.2.10"
        bridge = ("<interface type='bridge' name='br0'><protocol family='ipv4'><ip address='192.0.2.10' prefix='24'/>"
                  "</protocol><bridge><interface type='ethernet' name='eno1'/></bridge></interface>")
        other = "<interface type='ethernet' name='eno2'><protocol family='ipv4'><ip address='198.51.100.7' prefix='24'/></protocol></interface>"
        conn.wvm = MagicMock(**{"listAllInterfaces.return_value": [MagicMock(**{"XMLDesc.return_value": x}) for x in (bridge, other)],
                                "listAllDomains.return_value": [], "listAllNetworks.return_value": []})
        return conn

    def test_it_is_not_stopped(self):
        from vrtManager.interface import wvmInterface
        from vrtManager.util import OperationError

        for name in ("br0", "eno1"):
            conn = self.conn(wvmInterface)
            conn.iface = MagicMock(**{"name.return_value": name})
            with self.subTest(name), self.assertRaisesRegex(OperationError, "carries the address this panel reaches the host by"):
                conn.stop_iface()
            conn.iface.destroy.assert_not_called()
        conn.iface.name.return_value = "eno2"
        conn.stop_iface()
        conn.iface.destroy.assert_called_once_with()

    def test_a_bridge_over_it_keeps_the_address(self):
        from vrtManager.util import OperationError

        def create(netdev, ipv4_type, ipv4_addr="", ipv6_type="none", ipv6_addr=""):
            conn = self.conn(wvmInterfaces)
            conn.define_iface = MagicMock()
            conn.get_iface = MagicMock(side_effect=no_interface(netdev))
            conn.create_iface("br1", "bridge", "onboot", netdev, ipv4_type, ipv4_addr, "", ipv6_type, ipv6_addr, "", "on", 0)
            return conn.define_iface

        for kwargs in ({"ipv4_type": "none"}, {"ipv4_type": "static", "ipv4_addr": "192.0.2.11/24"},
                       {"ipv4_type": "none", "ipv6_type": "static", "ipv6_addr": "2001:db8::10/64"},
                       # DHCP of the other family leaves the panel's IPv4 address behind
                       {"ipv4_type": "none", "ipv6_type": "dhcp"}):
            with self.subTest(**kwargs), self.assertRaisesRegex(OperationError, "Device eno1 carries the address"):
                create("eno1", **kwargs)
        for netdev, kwargs in (("eno1", {"ipv4_type": "static", "ipv4_addr": "192.0.2.10/24"}),
                               ("eno1", {"ipv4_type": "dhcp"}), ("eno2", {"ipv4_type": "none"})):
            with self.subTest(netdev=netdev, **kwargs):
                self.assertTrue(create(netdev, **kwargs).called)

    def test_one_whose_leased_addresses_libvirt_cannot_tell_is_kept(self):
        # netcf gives no running XML for a virtio card ("link speed -1"): its saved one has no lease
        from vrtManager.interface import panel_devices
        import ipaddress

        err = libvirt.libvirtError("Invalid value for attribute 'speed' in element 'link': '-1'")
        err.err = (libvirt.VIR_ERR_XML_ERROR, libvirt.VIR_FROM_INTERFACE, str(err), 2, None, None, None, 0, 0)
        saved = "<interface type='ethernet' name='eth0'><protocol family='ipv4'><dhcp/></protocol></interface>"
        eth0 = MagicMock(**{"XMLDesc.side_effect": lambda flags=0: saved if flags else (_ for _ in ()).throw(err)})
        conn = MagicMock(**{"listAllInterfaces.return_value": [eth0]})
        self.assertEqual(panel_devices(conn, {ipaddress.ip_address("192.0.2.10")}), {"eth0"})
        # a panel on the host itself is not cut off by it
        self.assertEqual(panel_devices(conn, {ipaddress.ip_address("127.0.0.1")}), set())
