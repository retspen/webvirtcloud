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

    def test_other_lookup_errors_are_not_hidden(self):
        conn = wvmInterfaces.__new__(wvmInterfaces)
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
        conn.wvm = MagicMock()
        conn.define_iface = MagicMock()
        iface = conn.define_iface.return_value
        iface.create.side_effect = libvirt.libvirtError("failed to bring up br1")
        with self.assertRaises(libvirt.libvirtError):
            conn.create_iface("br1", "ethernet", "onboot", "", "none", "", "", "none", "", "", "on", 0)
        conn.wvm.changeRollback.assert_called_once_with(0)
        conn.wvm.changeCommit.assert_not_called()
