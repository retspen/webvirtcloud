"""A network's DHCP range is changed while the network is stopped, and the
page says so only when it was: a running network, a network without a
range, an address it does not have or a range outside its subnet is
refused with the reason. Runs on a private libvirt test driver:
"test:///default" is shared by the whole process."""

import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from networks.tests.driver import without_inactive_flag
from django.urls import reverse
from lxml import etree

NODE = """<node>
  <network><name>lab</name><bridge name='virbr9'/>
    <ip address='192.0.2.1' netmask='255.255.255.0'><dhcp><range start='192.0.2.10' end='192.0.2.20'/></dhcp></ip>
  </network>
  <network><name>plain</name><bridge name='virbr8'/><ip address='198.51.100.1' netmask='255.255.255.0'/></network>
</node>"""


class DhcpRangeTests(TestCase):
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
        self.compute = Compute.objects.create(name="dhcp", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("dhcp", "dhcp@example.com", "pw"))

    def change(self, network, index="0", start="192.0.2.30", end="192.0.2.40"):
        response = self.client.post(reverse("network", args=[self.compute.id, network]), {
            "modify_dhcp_range": "", "range_start": start, "range_end": end, "ip_index": index})
        return [str(m) for m in get_messages(response.wsgi_request)]

    def dhcp_range(self, network):
        xml = etree.fromstring(self.conn.networkLookupByName(network).XMLDesc(0))
        return xml.xpath("ip/dhcp/range/@start|ip/dhcp/range/@end")

    def test_a_stopped_network_gets_the_new_range(self):
        self.conn.networkLookupByName("lab").destroy()
        self.assertEqual(self.change("lab"), ["The DHCP range is changed"])
        self.assertEqual(self.dhcp_range("lab"), ["192.0.2.30", "192.0.2.40"])

    def test_a_running_network_is_refused(self):
        messages = self.change("lab")
        self.assertEqual(messages, ["Stop network lab to change its DHCP range"])
        self.assertEqual(self.dhcp_range("lab"), ["192.0.2.10", "192.0.2.20"])

    def test_a_network_without_a_range_or_an_unknown_family_is_refused(self):
        self.conn.networkLookupByName("lab").destroy()
        self.conn.networkLookupByName("plain").destroy()
        self.assertEqual(self.change("plain")[-1], "This address of network plain has no DHCP range")
        self.assertEqual(self.change("lab", index="1")[-1], "Network lab has no such address")
        self.assertEqual(self.change("lab", index="x")[-1], "Network lab has no such address")
        self.assertEqual(self.dhcp_range("lab"), ["192.0.2.10", "192.0.2.20"])

    def test_a_range_outside_the_subnet_or_backwards_is_refused(self):
        self.conn.networkLookupByName("lab").destroy()
        self.assertEqual(self.change("lab", end="198.51.100.9")[-1], "The range end 198.51.100.9 is not in 192.0.2.0/24")
        self.assertEqual(self.change("lab", start="192.0.2.1")[-1], "192.0.2.1 is the host's own address on the network")
        self.assertEqual(self.change("lab", start="192.0.2.50")[-1], "The range starts at 192.0.2.50, after its end 192.0.2.40")
        self.assertEqual(self.dhcp_range("lab"), ["192.0.2.10", "192.0.2.20"])
