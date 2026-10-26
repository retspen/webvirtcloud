"""A new network with fixed addresses gets one per address of its DHCP range,
for any /24 or smaller subnet; a network that does not start is not left
defined; fixed addresses change on a stopped network and may have no MAC."""

from unittest.mock import patch

from django.test import SimpleTestCase
from libvirt import VIR_NETWORK_UPDATE_AFFECT_CONFIG, VIR_NETWORK_UPDATE_AFFECT_LIVE, libvirtError
from lxml import etree
from networks.forms import AddNetPool
from vrtManager.network import network_size, wvmNetwork, wvmNetworks

NET = ("<network><name>n1</name><ip address='192.0.2.1' netmask='255.255.255.0'><dhcp>"
       "<range start='192.0.2.2' end='192.0.2.254'/><host name='paul' ip='192.0.2.20'/></dhcp></ip></network>")


class NetworkChangeTests(SimpleTestCase):
    def setUp(self):
        patcher = patch("vrtManager.connection.connection_manager.get_connection")
        self.wvm = patcher.start().return_value
        self.addCleanup(patcher.stop)

    def create(self, subnet):
        gateway, mask, dhcp = network_size(subnet, True)
        wvmNetworks("host", "login", "pw", 1).create_network(
            "n1", "nat", True, gateway, mask, dhcp, False, None, None, None, "", False, fixed=True)
        return etree.fromstring(self.wvm.networkDefineXML.call_args.args[0])

    def test_fixed_addresses_cover_the_dhcp_range(self):
        ip = self.create("192.0.2.128/25").find("ip")
        # the gateway is the subnet's first address, not one ending in .1
        self.assertEqual((ip.get("address"), ip.get("netmask")), ("192.0.2.129", "255.255.255.128"))
        hosts = ip.xpath("dhcp/host/@ip")
        self.assertEqual((hosts[0], hosts[-1], len(hosts)), ("192.0.2.130", "192.0.2.254", 125))

    def test_fixed_addresses_need_a_small_subnet(self):
        form = AddNetPool({"name": "n1", "forward": "nat", "subnet": "198.51.0.0/16", "dhcp4": True, "fixed": True})
        self.assertIn("fixed", form.errors)

    def test_a_network_that_does_not_start_is_undefined(self):
        net = self.wvm.networkDefineXML.return_value
        net.create.side_effect = libvirtError("network is already in use by interface virbr0")
        with self.assertRaises(libvirtError):
            self.create("192.0.2.0/24")
        net.undefine.assert_called_once_with()
        net.setAutostart.assert_not_called()

    def test_a_stopped_network_changes_its_configuration_only(self):
        net = self.wvm.networkLookupByName.return_value
        net.XMLDesc.return_value = NET
        for active, flags in ((False, VIR_NETWORK_UPDATE_AFFECT_CONFIG),
                              (True, VIR_NETWORK_UPDATE_AFFECT_CONFIG | VIR_NETWORK_UPDATE_AFFECT_LIVE)):
            with self.subTest(active=active):
                net.isActive.return_value = active
                wvmNetwork("host", "login", "pw", 1, "n1").delete_fixed_address("192.0.2.20")
                # a host with only a name is named as it is, without an empty MAC
                self.assertEqual(net.update.call_args.args[3:], ('<host name="paul" ip="192.0.2.20"/>', flags))
