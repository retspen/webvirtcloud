"""A network's addresses are read from its XML however libvirt writes it,
each <ip> by its own index; a change starts from the saved definition, so
two in a row keep each other; a fixed address is found by the address it
had and checked against its subnet; the XML editor defines only this
network; a network that does not start is not left defined. Runs on a
private libvirt test driver: "test:///default" is shared by the whole
process."""

import tempfile
from unittest.mock import MagicMock, patch

import libvirt
from django.test import SimpleTestCase
from networks.tests.driver import without_inactive_flag
from lxml import etree
from vrtManager.network import ip_networks, network_size, wvmNetwork, wvmNetworks
from vrtManager.util import OperationError

NODE = """<node>
  <network><name>lab</name><bridge name='virbr9'/>
    <ip family='ipv6' address='2001:db8:1::1' prefix='64'/>
    <ip family='ipv4' address='192.0.2.1' netmask='255.255.255.0'><dhcp><range start='192.0.2.10' end='192.0.2.20'/>
      <host name='paul' ip='192.0.2.30'/><host mac='52:54:00:00:00:31' ip='192.0.2.31'/></dhcp></ip>
  </network>
</node>"""


class AddressTests(SimpleTestCase):
    def test_an_address_without_a_prefix_takes_libvirts(self):
        tree = etree.fromstring("<network><ip address='192.0.2.1'/><ip address='10.1.2.3'/><ip family='ipv6' address='2001:db8::1'/></network>")
        self.assertEqual([str(ip["subnet"]) for ip in ip_networks(tree)], ["192.0.2.0/24", "10.0.0.0/8", "2001:db8::/64"])

    def test_every_way_libvirt_writes_an_address(self):
        compact = "<network><ip address='192.0.2.1' netmask='255.255.255.0'/></network>"
        static = ("<network><ip address='192.0.2.1' prefix='24'><dhcp><host mac='52:54:00:00:00:01' ip='192.0.2.5'/>"
                  "</dhcp></ip><ip family='ipv6' address='2001:db8::1' prefix='64'/></network>")
        (ip,) = ip_networks(etree.fromstring(compact))
        self.assertEqual((ip["index"], ip["family"], str(ip["subnet"]), ip["dhcp"]), (0, "ipv4", "192.0.2.0/24", False))
        v4, v6 = ip_networks(etree.fromstring(static))
        # DHCP with fixed addresses only is DHCP too
        self.assertEqual((v4["dhcp"], v4["range"], v4["hosts"][0]["ip"]), (True, None, "192.0.2.5"))
        self.assertEqual((v6["index"], v6["family"], str(v6["subnet"])), (1, "ipv6", "2001:db8::/64"))


class NetworkChangeTests(SimpleTestCase):
    def setUp(self):
        node = tempfile.NamedTemporaryFile("w", suffix=".xml")
        self.addCleanup(node.close)
        node.write(NODE)
        node.flush()
        self.conn = libvirt.open(f"test://{node.name}")
        self.addCleanup(self.conn.close)
        patcher = patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)
        without_inactive_flag(self)

    def network(self):
        return wvmNetwork("localhost", "", "", 4, "lab")

    def saved(self):
        return etree.fromstring(self.conn.networkLookupByName("lab").XMLDesc(libvirt.VIR_NETWORK_XML_INACTIVE))

    def test_the_page_reads_the_xml_once(self):
        net = self.network()
        with patch.object(net.net, "XMLDesc", wraps=net.net.XMLDesc) as xml:
            net.get_ip_networks(), net.get_network_forward(), net.get_network_mac(), net.get_qos()
            net.get_bridge_device()
        self.assertEqual(xml.call_count, 1)

    def test_the_ipv4_address_after_an_ipv6_one_keeps_its_index(self):
        ipv6, ipv4 = self.network().get_ip_networks()
        self.assertEqual((ipv6["family"], ipv4["family"], ipv4["index"]), ("ipv6", "ipv4", 1))
        self.network().modify_fixed_address(1, "", "web", "192.0.2.40", "52:54:00:00:00:40")
        self.assertEqual(self.saved().xpath("ip[2]/dhcp/host[last()]/@ip"), ["192.0.2.40"])

    def test_two_changes_in_a_row_keep_each_other(self):
        # a running network keeps its running definition until restarted: a
        # change made from it would drop the change saved before
        net = self.network()
        running = net.net.XMLDesc(0)
        saved = [running]
        net.net = MagicMock(**{"XMLDesc.side_effect": lambda flags=0: saved[0] if flags else running})
        with patch.object(self.conn, "networkDefineXML", side_effect=lambda xml: saved.__setitem__(0, xml)):
            net.set_qos("inbound", 100, 200, 300)
            net.set_qos("outbound", 10, 20, 30)
        self.assertEqual(etree.fromstring(saved[0]).xpath("bandwidth/*/@average"), ["100", "10"])

    def test_a_fixed_address_is_found_by_the_address_it_had(self):
        net = self.network()
        # a name-only entry changes too, and the one deleted is the one it was
        net.modify_fixed_address(1, "192.0.2.30", "paul", "192.0.2.32", "")
        self.assertEqual(self.saved().xpath("ip[2]/dhcp/host/@ip"), ["192.0.2.31", "192.0.2.32"])
        net.modify_fixed_address(1, "192.0.2.31", "db", "192.0.2.33", "52:54:00:00:00:31")
        net.delete_fixed_address(1, "192.0.2.32")
        self.assertEqual([dict(h.attrib) for h in self.saved().xpath("ip[2]/dhcp/host")],
                         [{"mac": "52:54:00:00:00:31", "name": "db", "ip": "192.0.2.33"}])
        with self.assertRaisesRegex(OperationError, "has no fixed address 192.0.2.99"):
            net.delete_fixed_address(1, "192.0.2.99")

    def test_a_change_keeps_what_the_page_does_not_show_and_touches_no_other_entry(self):
        net = self.network()
        conn = self.conn.networkLookupByName("lab")
        conn.destroy()
        saved = conn.XMLDesc(0).replace("<host mac='52:54:00:00:00:31' ip='192.0.2.31'/>",
                                        "<host mac='52:54:00:00:00:31' id='01:02:03:04' ip='192.0.2.31'><lease expiry='1' unit='hours'/></host>")
        self.conn.networkDefineXML(saved)
        net = self.network()
        # the name of another entry is refused before anything changes
        with self.assertRaisesRegex(OperationError, "The name paul has another fixed address, 192.0.2.30"):
            net.modify_fixed_address(1, "192.0.2.31", "paul", "192.0.2.35", "52:54:00:00:00:31")
        with self.assertRaisesRegex(OperationError, "52:54:00:00:00:31 has another fixed address"):
            net.modify_fixed_address(1, "192.0.2.30", "paul", "192.0.2.30", "52:54:00:00:00:31")
        net.modify_fixed_address(1, "192.0.2.31", "web", "192.0.2.35", "52:54:00:00:00:31")
        (host,) = self.saved().xpath("ip[2]/dhcp/host[@ip='192.0.2.35']")
        self.assertEqual((host.get("id"), host.xpath("string(lease/@expiry)"), host.get("name")), ("01:02:03:04", "1", "web"))
        self.assertEqual(self.saved().xpath("ip[2]/dhcp/host/@ip"), ["192.0.2.30", "192.0.2.35"])

    def test_an_ipv6_entry_known_by_its_duid_changes(self):
        self.conn.networkDefineXML(
            "<network><name>six</name><bridge name='virbr5'/><ip family='ipv6' address='2001:db8:5::1' prefix='64'>"
            "<dhcp><host id='00:01:00:01:aa:bb' ip='2001:db8:5::10'/></dhcp></ip></network>")
        net = wvmNetwork("localhost", "", "", 4, "six")
        net.modify_fixed_address(0, "2001:db8:5::10", "", "2001:db8:5::11", "00:01:00:01:aa:bb")
        saved = etree.fromstring(self.conn.networkLookupByName("six").XMLDesc(0))
        self.assertEqual([dict(h.attrib) for h in saved.xpath("ip/dhcp/host")], [{"id": "00:01:00:01:aa:bb", "ip": "2001:db8:5::11"}])

    def test_an_entry_gone_meanwhile_is_not_added_anew(self):
        with self.assertRaisesRegex(OperationError, "is gone meanwhile"):
            self.network().modify_fixed_address(1, "192.0.2.99", "x", "192.0.2.40", "")
        self.assertEqual(self.saved().xpath("ip[2]/dhcp/host/@ip"), ["192.0.2.30", "192.0.2.31"])

    def test_a_running_network_saved_with_other_addresses_is_not_changed_live(self):
        # parentIndex would name another <ip> of the running network
        net = self.network()
        net.net = MagicMock(**{"isActive.return_value": 1, "name.return_value": "lab",
                               "XMLDesc.side_effect": lambda flags=0: NODE.split("<node>")[1].split("</node>")[0]
                               if not flags else "<network><name>lab</name><ip address='192.0.2.1' netmask='255.255.255.0'/></network>"})
        with self.assertRaisesRegex(OperationError, "runs with other addresses than it has saved"):
            net.update(0, 0, "<host/>", 0)
        net.net.update.assert_not_called()

    def test_the_xml_editor_expands_no_entity(self):
        # a file of the panel's host named by an external entity is not read into the check
        net = self.network()
        xml = ('<!DOCTYPE network [<!ENTITY name SYSTEM "file:///etc/hostname">]>'
               "<network><name>&name;</name></network>")
        with self.assertRaisesRegex(OperationError, "must define network lab"):
            net.edit_network(xml)

    def test_the_xml_editor_takes_an_encoding_declaration(self):
        self.conn.networkLookupByName("lab").destroy()
        net = self.network()
        net.edit_network('<?xml version="1.0" encoding="UTF-8"?>\n' + net.config_xml().replace("virbr9", "virbr6"))
        self.assertEqual(self.saved().xpath("bridge/@name"), ["virbr6"])

    def test_a_fixed_address_is_of_the_subnet_and_its_own(self):
        net = self.network()
        for address, why in (("198.51.100.5", "is not in 192.0.2.0/24"), ("192.0.2.1", "the host's own address"),
                             ("192.0.2.31", "another entry's fixed address"), ("x", "is not an IP address")):
            with self.subTest(address=address), self.assertRaisesRegex(OperationError, why):
                net.modify_fixed_address(1, "192.0.2.30", "paul", address, "")
        self.assertIs(net.modify_fixed_address(1, "192.0.2.30", "paul", "192.0.2.30", ""), False)

    def test_the_xml_editor_defines_this_network_only(self):
        self.conn.networkLookupByName("lab").destroy()  # its definition read back at once
        net = self.network()
        xml = net.config_xml()
        for other, why in ((xml.replace("<name>lab</name>", "<name>other</name>"), "must define network lab"),
                           (xml.replace(net.net.UUIDString(), "11111111-2222-3333-4444-555555555555"), "keep the network's UUID"),
                           ("<network>", "not valid")):
            with self.subTest(why=why), self.assertRaisesRegex(OperationError, why):
                net.edit_network(other)
        net.edit_network(xml.replace("virbr9", "virbr7"))
        self.assertEqual(self.saved().xpath("bridge/@name"), ["virbr7"])

    def test_a_network_that_does_not_start_is_undefined(self):
        gateway, mask, dhcp = network_size("192.0.2.0/24", True)
        with patch.object(libvirt.virNetwork, "create", side_effect=libvirt.libvirtError("in use by virbr0")):
            with self.assertRaises(libvirt.libvirtError):
                wvmNetworks("localhost", "", "", 4).create_network(
                    "n1", "nat", True, gateway, mask, dhcp, False, None, None, None, "", False)
        self.assertNotIn("n1", self.conn.listDefinedNetworks() + self.conn.listNetworks())
