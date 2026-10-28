"""Network changes write rows on the Logs page. Runs on a private libvirt test driver."""

import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from networks.tests.driver import without_inactive_flag
from django.urls import reverse

from logs.models import Logs

NODE = """<node>
  <network><name>lab</name><bridge name='virbr9'/>
    <ip address='192.0.2.1' netmask='255.255.255.0'><dhcp><range start='192.0.2.10' end='192.0.2.20'/></dhcp></ip>
  </network>
</node>"""


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class NetworkRowTests(TestCase):
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
        self.compute = Compute.objects.create(name="c1", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("audit-admin", "a@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row
        self.url = reverse("network", args=[self.compute.id, "lab"])

    def post(self, data):
        return self.client.post(self.url, data)

    def test_network_actions(self):
        xml = self.conn.networkLookupByName("lab").XMLDesc(0)
        self.post({"stop": ""})
        self.post({"modify_dhcp_range": "", "range_start": "192.0.2.30", "range_end": "192.0.2.40", "ip_index": "0"})
        self.post({"start": ""})
        self.post({"set_autostart": ""})
        self.post({"unset_autostart": ""})
        self.post({"modify_fixed_address": "", "name": "web-1", "address": "192.0.2.31",
                   "mac": "52:54:00:00:00:31", "ip_index": "0"})
        self.post({"delete_fixed_address": "", "original": "192.0.2.31", "ip_index": "0"})
        self.post({"set_qos": "", "qos_direction": "inbound", "qos_average": "100"})
        self.post({"unset_qos": "", "qos_direction": "inbound"})
        self.post({"edit_network": "", "edit_xml": xml})
        self.post({"stop": ""})
        self.post({"delete": ""})
        self.assertEqual(rows(), [
            ("Network lab: stop", True),
            ("Network lab: set DHCP range", True),
            ("Network lab: start", True),
            ("Network lab: autostart on", True),
            ("Network lab: autostart off", True),
            ("Network lab: set fixed address 192.0.2.31", True),
            ("Network lab: delete fixed address 192.0.2.31", True),
            ("Network lab: set QoS inbound", True),
            ("Network lab: unset QoS inbound", True),
            ("Network lab: change XML", True),
            ("Network lab: stop", True),
            ("Network lab: delete", True),
        ])
        self.assertFalse(Logs.objects.filter(message__contains="<network").exists())
        self.assertEqual(set(Logs.objects.values_list("host", flat=True)), {"c1"})

    def test_a_refused_network_stop(self):
        error = "Requested operation is not valid: network is in use"
        with patch("vrtManager.network.wvmNetwork.stop", side_effect=libvirt.libvirtError(error)):
            response = self.post({"stop": ""})
        self.assertIn(error, [str(m) for m in get_messages(response.wsgi_request)])
        self.assertEqual(rows(), [(f"Network lab: stop: {error}", False)])

    def test_a_refused_network_delete(self):
        error = "Requested operation is not valid: network is in use"
        with patch("vrtManager.network.wvmNetwork.delete", side_effect=libvirt.libvirtError(error)):
            response = self.post({"delete": ""})
        self.assertIn(error, [str(m) for m in get_messages(response.wsgi_request)])
        self.assertEqual(rows(), [(f"Network lab: delete: {error}", False)])

    def test_network_create(self):
        url = reverse("networks", args=[self.compute.id])
        self.client.post(url, {"create": "", "name": "audit-net", "forward": "nat", "subnet": "198.51.100.0/24",
                               "dhcp4": "on"})
        self.client.post(url, {"create": "", "name": "bad name!", "forward": "nat"})  # invalid form
        response = self.client.post(url, {"create": "", "name": "lab", "forward": "nat", "subnet": "203.0.113.0/24"})
        self.assertIn("* This host has a network of that name", [str(m) for m in get_messages(response.wsgi_request)])
        self.assertEqual(rows(), [("Network audit-net: add", True), ("Network lab: add: name already in use", False)])
