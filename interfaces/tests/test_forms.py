"""Host interface form: every value is validated before it goes into the interface XML."""


from django.test import SimpleTestCase

from interfaces.forms import AddInterface
from interfaces.tests.fakes import BASE

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


class EthernetDeviceTestCase(SimpleTestCase):
    def test_an_ethernet_interface_needs_no_bridge_member(self):
        self.assertTrue(form(itype="ethernet", name="eth0", netdev="", ipv6_type="none").is_valid())

    def test_a_bridge_needs_a_member(self):
        f = form(netdev="", ipv6_type="none")
        self.assertFalse(f.is_valid())
        self.assertIn("netdev", f.errors)
