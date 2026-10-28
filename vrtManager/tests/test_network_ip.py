import sys
import unittest
from unittest.mock import MagicMock

try:
    from django.conf import settings
    if not settings.configured:
        settings.configure(MAC_OUI="52:54:10")
except ImportError:
    django_mock = MagicMock()
    django_mock.conf.settings.MAC_OUI = "52:54:10"
    sys.modules["django"] = django_mock
    sys.modules["django.conf"] = django_mock.conf

from lxml import etree
from vrtManager.network import ip_networks, network_size


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


class TestIpNetworks(unittest.TestCase):
    """A network's addresses (ip_networks): subnet, DHCP range and fixed addresses of each family."""

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

    def test_dual_stack(self):
        v4, v6 = ip_networks(etree.fromstring(self.DUAL_STACK_XML))
        self.assertEqual((str(v4["subnet"]), v4["range"]), ("192.168.100.0/24", ("192.168.100.2", "192.168.100.254")))
        self.assertEqual(v4["hosts"], [{"ip": "192.168.100.50", "mac": "52:54:00:12:34:56", "id": None, "name": "vm1"}])
        self.assertEqual((str(v6["subnet"]), v6["range"]), ("2001:db8:ca2:2::/64", ("2001:db8:ca2:2::100", "2001:db8:ca2:2::1ff")))
        self.assertEqual(v6["hosts"][0]["id"], "0:1:0:1")

    def test_no_address(self):
        self.assertEqual(ip_networks(etree.fromstring("<network><name>isolated</name><bridge name='virbr1'/></network>")), [])


if __name__ == "__main__":
    unittest.main()
