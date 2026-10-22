"""A network's DHCP range is changed while the network is stopped, and the
page says so only when it was: a running network, a network without a
range or an unknown address family is refused with the reason. Runs on a
private libvirt test driver: "test:///default" is shared by the whole
process."""

import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
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
        self.compute = Compute.objects.create(name="dhcp", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("dhcp", "dhcp@example.com", "pw"))

    def change(self, network, family="ipv4"):
        response = self.client.post(reverse("network", args=[self.compute.id, network]), {
            "modify_dhcp_range": "", "range_start": "192.0.2.30", "range_end": "192.0.2.40", "family": family})
        return [str(m) for m in get_messages(response.wsgi_request)]

    def dhcp_range(self, network):
        xml = etree.fromstring(self.conn.networkLookupByName(network).XMLDesc(0))
        return xml.xpath("ip/dhcp/range/@start|ip/dhcp/range/@end")

    def test_a_stopped_network_gets_the_new_range(self):
        self.conn.networkLookupByName("lab").destroy()
        self.assertEqual(self.change("lab"), ["IPV4 DHCP Range is Changed."])
        self.assertEqual(self.dhcp_range("lab"), ["192.0.2.30", "192.0.2.40"])

    def test_a_running_network_is_refused(self):
        messages = self.change("lab")
        self.assertEqual(messages, ["Stop network lab to change its DHCP range"])
        self.assertEqual(self.dhcp_range("lab"), ["192.0.2.10", "192.0.2.20"])

    def test_a_network_without_a_range_or_an_unknown_family_is_refused(self):
        self.conn.networkLookupByName("lab").destroy()
        self.conn.networkLookupByName("plain").destroy()
        self.assertEqual(self.change("plain"), ["Network plain has no ipv4 DHCP range"])
        self.assertEqual(self.change("lab", family="ipx"), ["Network lab has no ipx DHCP range"])
        self.assertEqual(self.dhcp_range("lab"), ["192.0.2.10", "192.0.2.20"])
