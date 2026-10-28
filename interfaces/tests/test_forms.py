"""Host interface form: every value is validated before it goes into the interface XML."""

from unittest.mock import MagicMock, patch

import libvirt

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from lxml import etree, html
from vrtManager.interface import wvmInterfaces

from interfaces.forms import AddInterface

BASE = {
    "name": "br1", "itype": "bridge", "start_mode": "onboot", "netdev": "eth1",
    "ipv4_type": "static", "ipv4_addr": "192.0.2.10/24", "ipv4_gw": "192.0.2.1",
    "ipv6_type": "static", "stp": "on", "delay": 0,
}


# the host's network devices, as interfaces/views.py passes them
NETDEVS = ["eth0", "eth1", "enp129s0f0np0", "eth0.100", "bond-lan"]


def form(**values):
    return AddInterface(data={**BASE, **values}, netdevs=NETDEVS, members=NETDEVS)


class DefinedNameTestCase(SimpleTestCase):
    def test_an_interface_the_host_defines_is_not_replaced(self):
        defined = ["br0", "bond-lan"]  # as libvirt lists them
        for values in ({"name": "br0"}, {"name": "bond-lan", "itype": "ethernet", "netdev": ""}):
            with self.subTest(**values):
                f = AddInterface(data={**BASE, **values}, netdevs=NETDEVS, members=NETDEVS, defined=defined)
                self.assertEqual(f.errors["name"], [f"The host already defines interface {values['name']}"])
        self.assertTrue(AddInterface(data={**BASE, "ipv6_type": "none"}, netdevs=NETDEVS, members=NETDEVS, defined=defined).is_valid())


class Ipv6FormTestCase(SimpleTestCase):
    def test_valid_addresses_are_normalized(self):
        f = form(ipv6_addr="2001:DB8::10/64", ipv6_gw="2001:DB8::1")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["ipv6_addr"], "2001:db8::10/64")
        self.assertEqual(f.cleaned_data["ipv6_gw"], "2001:db8::1")

    def test_address_without_prefix_gets_one(self):
        f = form(ipv6_addr="2001:db8::10", ipv6_gw="")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["ipv6_addr"], "2001:db8::10/128")

    def test_values_that_only_start_like_an_address_are_rejected(self):
        for field, value in (
            ("ipv6_addr", "2001:db8::10/64'/><evil/>"),
            ("ipv6_gw", "2001:db8::1'/><evil/>"),
            ("ipv6_addr", "2001:db8::zz/64"),
            ("ipv6_addr", "192.0.2.10/24"),
        ):
            with self.subTest(field=field, value=value):
                f = form(**{"ipv6_addr": "2001:db8::10/64", "ipv6_gw": "", field: value})
                self.assertFalse(f.is_valid())
                self.assertIn(field, f.errors)

    def test_static_needs_an_address(self):
        f = form(ipv6_addr="", ipv6_gw="")
        self.assertFalse(f.is_valid())
        self.assertIn("ipv6_addr", f.errors)

    def test_dhcp_needs_no_address(self):
        self.assertTrue(form(ipv6_type="dhcp", ipv6_addr="", ipv6_gw="").is_valid())


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


class Ipv4FormTestCase(SimpleTestCase):
    def test_dhcp_and_none_need_no_address(self):
        for ipv4_type in ("dhcp", "none"):
            with self.subTest(ipv4_type=ipv4_type):
                f = form(ipv4_type=ipv4_type, ipv4_addr="", ipv4_gw="", ipv6_type="none")
                self.assertTrue(f.is_valid(), f.errors)

    def test_valid_address_and_gateway(self):
        f = form(ipv4_addr="192.0.2.10/24", ipv4_gw="192.0.2.1", ipv6_type="none")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["ipv4_addr"], "192.0.2.10/24")

    def test_address_without_prefix_gets_one(self):
        f = form(ipv4_addr="192.0.2.10", ipv4_gw="", ipv6_type="none")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["ipv4_addr"], "192.0.2.10/32")

    def test_invalid_values_are_rejected(self):
        for field, value in (
            ("ipv4_addr", "192.0.2.300/24"),
            ("ipv4_addr", "192.0.2.10/24/1"),
            ("ipv4_addr", "192.0.2.10/33"),
            ("ipv4_gw", "192.0.2.300"),
            ("ipv4_gw", "192.0.2.1/24"),
        ):
            with self.subTest(field=field, value=value):
                f = form(**{"ipv6_type": "none", field: value})
                self.assertFalse(f.is_valid())
                self.assertIn(field, f.errors)

    def test_static_needs_an_address(self):
        f = form(ipv4_addr="", ipv4_gw="", ipv6_type="none")
        self.assertFalse(f.is_valid())
        self.assertIn("ipv4_addr", f.errors)


class InterfaceNameTestCase(SimpleTestCase):
    def test_linux_interface_names_are_accepted(self):
        for name in ("br0", "bond-lan", "br_mgmt", "vlan.100", "BR0", "a" * 15):
            with self.subTest(name=name):
                f = form(name=name, ipv6_type="none")
                self.assertTrue(f.is_valid(), f.errors)
        for netdev in ("enp129s0f0np0", "eth0.100", "bond-lan"):
            with self.subTest(netdev=netdev):
                f = form(netdev=netdev, ipv6_type="none")
                self.assertTrue(f.is_valid(), f.errors)

    def test_other_names_are_rejected(self):
        for field in ("name", "netdev"):
            for value in ("br 1", "br/1", "br'1", "br1\nx", "a" * 16, "", ".", ".."):
                with self.subTest(field=field, value=value):
                    f = form(**{"ipv6_type": "none", field: value})
                    self.assertFalse(f.is_valid())
                    self.assertIn(field, f.errors)

    def test_surrounding_whitespace_is_stripped(self):
        f = form(name="br1\n", ipv6_type="none")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["name"], "br1")

    def test_a_new_interface_name_has_no_alias_colon(self):
        f = form(name="br0:1", ipv6_type="none")
        self.assertFalse(f.is_valid())
        self.assertIn("name", f.errors)


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


class HostDeviceTestCase(SimpleTestCase):
    def test_a_bridge_member_must_be_a_host_device(self):
        for netdev in ("eth9", "eth0:1"):
            with self.subTest(netdev=netdev):
                f = form(netdev=netdev, ipv6_type="none")
                self.assertFalse(f.is_valid())
                self.assertIn("netdev", f.errors)

    def test_a_bridge_cannot_contain_itself(self):
        f = form(name="eth1", netdev="eth1", ipv6_type="none")
        self.assertFalse(f.is_valid())
        self.assertIn("netdev", f.errors)

    def test_an_ethernet_interface_configures_a_host_device(self):
        self.assertTrue(form(itype="ethernet", name="eth0", ipv6_type="none").is_valid())
        f = form(itype="ethernet", name="eth9", ipv6_type="none")
        self.assertFalse(f.is_valid())
        self.assertIn("name", f.errors)

    def test_an_ethernet_interface_is_no_device_of_another_interface(self):
        # netcf lists a bridge, not its members: eth1 is in br0 here
        f = AddInterface(data={**BASE, "itype": "ethernet", "name": "eth1", "ipv6_type": "none"},
                         netdevs=NETDEVS, members=["eth0"], defined=["br0"])
        self.assertFalse(f.is_valid())
        self.assertIn("name", f.errors)


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


class BridgeSettingsTestCase(SimpleTestCase):
    def test_a_bridge_needs_stp_and_a_delay(self):
        for field in ("stp", "delay"):
            with self.subTest(field=field):
                f = form(**{"ipv6_type": "none", field: ""})
                self.assertFalse(f.is_valid())
                self.assertIn(field, f.errors)

    def test_the_delay_is_not_negative(self):
        f = form(delay=-1, ipv6_type="none")
        self.assertFalse(f.is_valid())
        self.assertIn("delay", f.errors)


class AddressNotationTestCase(SimpleTestCase):
    def test_ipv4_netmask_notation_becomes_a_prefix(self):
        f = form(ipv4_addr="192.0.2.10/255.255.255.0", ipv6_type="none")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["ipv4_addr"], "192.0.2.10/24")

    def test_ipv6_scope_ids_are_rejected(self):
        for field, value in (("ipv6_addr", "fe80::1%eth0/64"), ("ipv6_gw", "fe80::1%eth0")):
            with self.subTest(field=field):
                f = form(**{"ipv6_addr": "2001:db8::10/64", "ipv6_gw": "", field: value})
                self.assertFalse(f.is_valid())
                self.assertIn(field, f.errors)


class CreateViewTestCase(TestCase):
    """The page validates the device against the host's devices before it
    defines an interface."""

    def test_only_a_host_device_becomes_a_bridge_member(self):
        admin = get_user_model().objects.create_superuser("iface_admin", "a@example.com", "x")
        compute = Compute.objects.create(name="iface-c", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.client.force_login(admin)
        for netdev, created in (("eth9", False), ("eth0", True)):
            with self.subTest(netdev=netdev), patch("interfaces.views.wvmInterfaces") as conn_cls:
                conn = conn_cls.return_value
                conn.get_ifaces_info.return_value = []
                conn.can_change_interfaces.return_value = True
                conn.get_net_devices.return_value = ["eth0", "eth1"]
                conn.get_member_candidates.return_value = ["eth0", "eth1"]
                self.client.post(
                    reverse("interfaces", args=[compute.id]),
                    {**BASE, "netdev": netdev, "ipv6_type": "none", "create": ""},
                )
                self.assertEqual(conn.create_iface.called, created)

    def test_unreadable_host_devices_are_reported_not_blamed_on_the_input(self):
        admin = get_user_model().objects.create_superuser("iface_admin2", "b@example.com", "x")
        compute = Compute.objects.create(name="iface-c2", hostname="127.0.0.1:1", login="root", password="", type=1)
        self.client.force_login(admin)
        with patch("interfaces.views.wvmInterfaces") as conn_cls:
            conn = conn_cls.return_value
            conn.get_ifaces_info.return_value = []
            conn.can_change_interfaces.return_value = True
            conn.get_net_devices.side_effect = RuntimeError("nodedev driver not running")
            response = self.client.post(
                reverse("interfaces", args=[compute.id]),
                {**BASE, "netdev": "eth0", "ipv6_type": "none", "create": ""},
            )
        self.assertFalse(conn.create_iface.called)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("nodedev driver not running" in m for m in messages), messages)
        self.assertFalse(any("not on this host" in m for m in messages), messages)


class UnchangeableHostTestCase(TestCase):
    """A host whose libvirt cannot change interfaces (udev backend) gets no
    create form and no start/stop/delete, only a note; posts change nothing."""

    NOTE = "does not support changing network interfaces"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("iface_ro", "ro@example.com", "x"))
        self.compute = Compute.objects.create(name="iface-ro", hostname="127.0.0.1:1", login="root", password="", type=1)

    def interfaces_page(self, changeable, post=None):
        with patch("interfaces.views.wvmInterfaces") as conn_cls:
            conn = conn_cls.return_value
            conn.get_ifaces_info.return_value = []
            conn.can_change_interfaces.return_value = changeable
            conn.get_net_devices.return_value = ["eth0", "eth1"]
            url = reverse("interfaces", args=[self.compute.id])
            response = self.client.post(url, post) if post else self.client.get(url)
        return conn, response.content.decode()

    def test_the_interfaces_page_offers_create_only_where_it_works(self):
        for changeable in (True, False):
            with self.subTest(changeable=changeable):
                conn, page = self.interfaces_page(changeable)
                self.assertEqual("#AddInterface" in page, changeable)
                self.assertEqual(self.NOTE in page, not changeable)
                # the devices are only the form's choices
                self.assertEqual(conn.get_net_devices.called, changeable)

    def test_a_create_post_creates_nothing(self):
        conn, page = self.interfaces_page(False, {**BASE, "netdev": "eth1", "ipv6_type": "none", "create": ""})
        conn.create_iface.assert_not_called()
        self.assertIn(self.NOTE, page)

    def interface_page(self, changeable, state, post=None):
        with patch("interfaces.views.wvmInterface") as conn_cls:
            conn = conn_cls.return_value
            conn.can_change_interfaces.return_value = changeable
            conn.is_active.return_value = state
            url = reverse("interface", args=[self.compute.id, "br0"])
            response = self.client.post(url, post) if post else self.client.get(url)
        return conn, response

    def test_the_interface_page_shows_the_state_without_actions(self):
        for state, shown in ((1, "Active"), (0, "Inactive")):
            with self.subTest(state=state):
                _conn, response = self.interface_page(False, state)
                page = response.content.decode()
                self.assertNotIn('name="start"', page)
                self.assertNotIn('name="stop"', page)
                state_cell = html.fromstring(page).xpath("//dt[normalize-space()='State']/following-sibling::dd[1]")[0]
                self.assertEqual(state_cell.text_content().strip(), shown)
                self.assertIn(self.NOTE, page)
        _conn, response = self.interface_page(True, 0)
        self.assertIn('name="start"', response.content.decode())

    def test_a_host_that_could_not_be_read_offers_nothing(self):
        # not knowing whether the host can change interfaces is not a yes
        with patch("interfaces.views.wvmInterface", side_effect=libvirt.libvirtError("unreachable")):
            page = self.client.get(reverse("interface", args=[self.compute.id, "br0"])).content.decode()
        self.assertNotIn(self.NOTE, page)
        self.assertNotIn("Interface start/stop/delete form", page)

    def test_start_stop_and_delete_posts_change_nothing(self):
        for action in ("start", "stop", "delete"):
            with self.subTest(action=action):
                conn, response = self.interface_page(False, 1, {action: ""})
                self.assertEqual(response.status_code, 200)
                for method in (conn.start_iface, conn.stop_iface, conn.delete_iface):
                    method.assert_not_called()


class EthernetDeviceTestCase(SimpleTestCase):
    def test_an_ethernet_interface_needs_no_bridge_member(self):
        self.assertTrue(form(itype="ethernet", name="eth0", netdev="", ipv6_type="none").is_valid())

    def test_a_bridge_needs_a_member(self):
        f = form(netdev="", ipv6_type="none")
        self.assertFalse(f.is_valid())
        self.assertIn("netdev", f.errors)
