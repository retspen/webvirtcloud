"""A network a VM needs is not stopped or deleted: stopping one a running VM
is on would cut that VM off, deleting one a VM's definition names would keep
that VM from starting. Runs on a private libvirt test driver: "test:///default"
is shared by the whole process."""

import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from networks.tests.driver import without_inactive_flag
from django.urls import reverse

NODE = """<node>
  <domain type='test'><name>net-user</name><memory>1024</memory><os><type>hvm</type></os>
    <devices><interface type='network'><source network='lab'/></interface></devices></domain>
  <network><name>lab</name><bridge name='virbr9'/><ip address='192.0.2.1' netmask='255.255.255.0'/></network>
</node>"""


class NetworkInUseTests(TestCase):
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
        compute = Compute.objects.create(name="net-use", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("net-use", "nu@example.com", "pw"))
        self.url = reverse("network", args=[compute.id, "lab"])

    def post(self, action):
        response = self.client.post(self.url, {action: ""}, HTTP_REFERER=f"http://testserver{self.url}")
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_a_network_a_running_vm_is_on_is_not_stopped(self):
        messages = self.post("stop")
        self.assertTrue(any("running VMs net-user" in m for m in messages), messages)
        self.assertTrue(self.conn.networkLookupByName("lab").isActive())
        self.conn.lookupByName("net-user").destroy()
        self.post("stop")
        self.assertFalse(self.conn.networkLookupByName("lab").isActive())

    def test_a_network_a_vm_definition_names_is_not_deleted(self):
        self.conn.lookupByName("net-user").destroy()
        self.conn.networkLookupByName("lab").destroy()
        messages = self.post("delete")
        self.assertTrue(any("net-user" in m and "would no longer start" in m for m in messages), messages)
        self.assertIn("lab", self.conn.listDefinedNetworks())
        self.conn.lookupByName("net-user").undefine()
        self.post("delete")
        self.assertNotIn("lab", self.conn.listDefinedNetworks())
