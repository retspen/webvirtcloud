import sys
import unittest
from unittest.mock import MagicMock

# Mock django if not installed so tests can run in minimal/standalone environments
if "django" not in sys.modules:
    django_mock = MagicMock()
    sys.modules["django"] = django_mock
    sys.modules["django.conf"] = django_mock

from vrtManager.network import network_size, wvmNetwork


class TestNetworkSize(unittest.TestCase):
    """Unit tests for the network_size function."""

    def test_ipv4_slash_24_with_dhcp(self):
        gateway, mask, dhcp_pool = network_size("192.168.100.0/24", dhcp=True)
        self.assertEqual(gateway, "192.168.100.1")
        self.assertEqual(mask, "255.255.255.0")
        self.assertIsNotNone(dhcp_pool)
        self.assertEqual(str(dhcp_pool[0]), "192.168.100.2")
        self.assertEqual(str(dhcp_pool[1]), "192.168.100.254")

    def test_ipv4_slash_24_without_dhcp(self):
        gateway, mask, dhcp_pool = network_size("192.168.100.0/24", dhcp=False)
        self.assertEqual(gateway, "192.168.100.1")
        self.assertEqual(mask, "255.255.255.0")
        self.assertIsNone(dhcp_pool)

    def test_ipv4_slash_16_with_dhcp(self):
        gateway, mask, dhcp_pool = network_size("172.16.0.0/16", dhcp=True)
        self.assertEqual(gateway, "172.16.0.1")
        self.assertEqual(mask, "255.255.0.0")
        self.assertIsNotNone(dhcp_pool)
        self.assertEqual(str(dhcp_pool[0]), "172.16.0.2")
        self.assertEqual(str(dhcp_pool[1]), "172.16.255.254")

    def test_ipv4_slash_28_with_dhcp(self):
        gateway, mask, dhcp_pool = network_size("10.0.0.0/28", dhcp=True)
        self.assertEqual(gateway, "10.0.0.1")
        self.assertEqual(mask, "255.255.255.240")
        self.assertIsNotNone(dhcp_pool)
        self.assertEqual(str(dhcp_pool[0]), "10.0.0.2")
        self.assertEqual(str(dhcp_pool[1]), "10.0.0.14")

    def test_ipv4_slash_30_with_dhcp(self):
        gateway, mask, dhcp_pool = network_size("10.0.0.0/30", dhcp=True)
        self.assertEqual(gateway, "10.0.0.1")
        self.assertEqual(mask, "255.255.255.252")
        self.assertIsNotNone(dhcp_pool)
        self.assertEqual(str(dhcp_pool[0]), "10.0.0.2")
        self.assertEqual(str(dhcp_pool[1]), "10.0.0.2")

    def test_ipv6_slash_64_with_dhcp(self):
        gateway, mask, dhcp_pool = network_size("2001:db8:ca2:2::/64", dhcp=True)
        self.assertEqual(gateway, "2001:db8:ca2:2::1")
        self.assertEqual(mask, "64")
        self.assertIsNotNone(dhcp_pool)
        self.assertEqual(str(dhcp_pool[0]), "2001:db8:ca2:2::100")
        self.assertEqual(str(dhcp_pool[1]), "2001:db8:ca2:2::1ff")

    def test_ipv6_slash_64_without_dhcp(self):
        gateway, mask, dhcp_pool = network_size("2001:db8:ca2:2::/64", dhcp=False)
        self.assertEqual(gateway, "2001:db8:ca2:2::1")
        self.assertEqual(mask, "64")
        self.assertIsNone(dhcp_pool)

    def test_invalid_subnet(self):
        with self.assertRaises(ValueError):
            network_size("invalid.subnet/99")


class DummyNetwork(wvmNetwork):
    """Subclass of wvmNetwork with mock XML for isolated IP method testing."""

    def __init__(self, xml_content):
        self._xml = xml_content
        self.parent_count = 2
        self.updates = []

    def _XMLDesc(self, flags):
        return self._xml

    def update(self, command, section, xml, parent_index, flags):
        self.updates.append((command, section, xml, parent_index, flags))


class TestWvmNetworkIPOperations(unittest.TestCase):
    """Unit tests for IP parsing, DHCP ranges, and host addresses in wvmNetwork."""

    DUAL_STACK_XML = """<network>
      <name>default</name>
      <ip address="192.168.100.1" netmask="255.255.255.0">
        <dhcp>
          <range start="192.168.100.2" end="192.168.100.254"/>
          <host mac="52:54:00:12:34:56" name="vm1" ip="192.168.100.50"/>
        </dhcp>
      </ip>
      <ip family="ipv6" address="2001:db8:ca2:2::1" prefix="64">
        <dhcp>
          <range start="2001:db8:ca2:2::100" end="2001:db8:ca2:2::1ff"/>
          <host id="0:1:0:1" name="vm2" ip="2001:db8:ca2:2::50"/>
        </dhcp>
      </ip>
    </network>"""

    NO_IP_XML = """<network>
      <name>isolated</name>
      <bridge name="virbr1"/>
    </network>"""

    def test_get_ip_networks_dual_stack(self):
        net = DummyNetwork(self.DUAL_STACK_XML)
        ip_networks = net.get_ip_networks()
        self.assertIn("ipv4", ip_networks)
        self.assertIn("ipv6", ip_networks)
        self.assertEqual(str(ip_networks["ipv4"]), "192.168.100.0/24")
        self.assertEqual(str(ip_networks["ipv6"]), "2001:db8:ca2:2::/64")

    def test_get_ip_networks_no_ip(self):
        net = DummyNetwork(self.NO_IP_XML)
        ip_networks = net.get_ip_networks()
        self.assertEqual(ip_networks, {})

    def test_get_dhcp_range_ipv4(self):
        net = DummyNetwork(self.DUAL_STACK_XML)
        dhcp = net.get_dhcp_range("ipv4")
        self.assertIsNotNone(dhcp)
        self.assertEqual(len(dhcp), 2)
        self.assertEqual(str(dhcp[0]), "192.168.100.2")
        self.assertEqual(str(dhcp[1]), "192.168.100.254")

    def test_get_dhcp_range_ipv6(self):
        net = DummyNetwork(self.DUAL_STACK_XML)
        dhcp = net.get_dhcp_range("ipv6")
        self.assertIsNotNone(dhcp)
        self.assertEqual(len(dhcp), 2)
        self.assertEqual(str(dhcp[0]), "2001:db8:ca2:2::100")
        self.assertEqual(str(dhcp[1]), "2001:db8:ca2:2::1ff")

    def test_get_dhcp_range_empty(self):
        net = DummyNetwork(self.NO_IP_XML)
        self.assertIsNone(net.get_dhcp_range("ipv4"))
        self.assertIsNone(net.get_dhcp_range("ipv6"))

    def test_get_dhcp_range_start_and_end(self):
        net = DummyNetwork(self.DUAL_STACK_XML)
        self.assertEqual(str(net.get_dhcp_range_start("ipv4")), "192.168.100.2")
        self.assertEqual(str(net.get_dhcp_range_end("ipv4")), "192.168.100.254")
        self.assertEqual(str(net.get_dhcp_range_start("ipv6")), "2001:db8:ca2:2::100")
        self.assertEqual(str(net.get_dhcp_range_end("ipv6")), "2001:db8:ca2:2::1ff")

    def test_modify_fixed_address_validation(self):
        net = DummyNetwork(self.DUAL_STACK_XML)
        # Invalid IP address must raise ValueError
        with self.assertRaises(ValueError):
            net.modify_fixed_address("bad_host", "999.999.999.999", "52:54:00:11:22:33", family="ipv4")

        with self.assertRaises(ValueError):
            net.modify_fixed_address("bad_host", "not-an-ip", "0:1:0:2", family="ipv6")


if __name__ == "__main__":
    unittest.main()
