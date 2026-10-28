"""The create-network form takes real subnets of the right IP version; one
it refuses is a field error, not a server error. Each mode needs its own
fields, a known mode only, and no subnet of another network of the host."""

from django.test import SimpleTestCase
from networks.forms import AddNetPool


def form(**fields):
    return AddNetPool({"name": "wvc-test-net", "forward": "nat", **fields})


class SubnetTests(SimpleTestCase):
    def test_subnets_are_accepted(self):
        for subnet in ("192.0.2.0/24", "192.0.2.0/30", "255.255.255.252/30"):
            with self.subTest(subnet=subnet):
                self.assertTrue(form(subnet=subnet, subnet6="2001:db8::/64", enable_ipv6=True).is_valid())

    def test_a_subnet_that_is_not_one_is_refused(self):
        for field, value in (
            ("subnet", "192.0.2.0/33"),
            ("subnet", "999.0.2.0/24"),
            ("subnet", "2001:db8::/64"),
            ("subnet6", "2001:db8::/129"),
            ("subnet6", "192.0.2.0/24"),
            # no room for a gateway, a DHCP range and a broadcast address
            ("subnet", "192.0.2.0"),
            ("subnet", "192.0.2.0/31"),
            ("subnet", "0.0.0.0/32"),
            ("subnet", "255.255.255.255/32"),
            # libvirt takes only /64 for IPv6
            ("subnet6", "2001:db8::"),
            ("subnet6", "2001:db8::/120"),
            ("subnet6", "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff/128"),
        ):
            with self.subTest(field=field, value=value):
                self.assertIn(field, form(**{field: value}).errors)


NETWORKS = [{"name": "default", "ips": [{"subnet": __import__("ipaddress").ip_network("192.168.122.0/24")}]}]


def errors(**fields):
    f = AddNetPool({"name": "wvc-test-net", **fields}, networks=NETWORKS)
    f.is_valid()
    return sorted(f.errors)


class ModeTests(SimpleTestCase):
    def test_each_mode_needs_its_fields(self):
        self.assertEqual(errors(forward="nat"), ["subnet"])
        self.assertEqual(errors(forward="route"), ["subnet"])
        self.assertEqual(errors(forward="none"), [])  # an isolated network may have no address
        self.assertEqual(errors(forward="bridge"), ["bridge_name"])
        self.assertEqual(errors(forward="macvtap"), ["bridge_name"])
        self.assertEqual(errors(forward="none", enable_ipv6=True), ["subnet6"])
        self.assertEqual(errors(forward="bogus", subnet="192.0.2.0/24"), ["forward"])
        self.assertEqual(errors(subnet="192.0.2.0/24"), ["forward"])  # no mode: an error, not a server error

    def test_a_bridge_takes_no_addresses_and_ipv6_needs_its_box(self):
        f = AddNetPool({"name": "br", "forward": "bridge", "bridge_name": "br0", "subnet": "192.0.2.0/24", "dhcp4": True})
        self.assertTrue(f.is_valid())
        self.assertEqual((f.cleaned_data["subnet"], f.cleaned_data["dhcp4"]), ("", False))
        f = AddNetPool({"name": "n", "forward": "nat", "subnet": "192.0.2.0/24", "subnet6": "2001:db8::/64"})
        self.assertTrue(f.is_valid())
        self.assertEqual(f.cleaned_data["subnet6"], "")

    def test_a_network_takes_no_name_or_subnet_of_another(self):
        self.assertEqual(errors(forward="nat", subnet="192.168.122.128/25"), ["subnet"])
        self.assertEqual(errors(forward="nat", subnet="192.168.0.0/16"), ["subnet"])
        self.assertEqual(errors(forward="nat", subnet="192.0.2.0/24"), [])
        f = AddNetPool({"name": "default", "forward": "none"}, networks=NETWORKS)
        self.assertTrue(f.has_error("name", "taken"))
