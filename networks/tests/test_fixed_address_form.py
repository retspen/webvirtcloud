"""The network page's fixed-address dialog takes real MAC addresses and host
names: the browser refuses what its pattern attributes do not match. Runs
on a private libvirt test driver."""

import re
import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import html
from networks.tests.driver import without_inactive_flag

NODE = """<node><network><name>lab</name><bridge name='virbr9'/>
  <ip address='192.0.2.1' netmask='255.255.255.0'><dhcp><range start='192.0.2.10' end='192.0.2.20'/></dhcp></ip>
</network></node>"""


class FixedAddressFormTests(TestCase):
    def test_macs_and_host_names_are_accepted(self):
        node = tempfile.NamedTemporaryFile("w", suffix=".xml")
        self.addCleanup(node.close)
        node.write(NODE)
        node.flush()
        conn = libvirt.open(f"test://{node.name}")
        self.addCleanup(conn.close)
        without_inactive_flag(self)
        compute = Compute.objects.create(name="fixed", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("fixed", "fixed@example.com", "pw"))
        with patch("vrtManager.connection.connection_manager.get_connection", return_value=conn):
            page = html.fromstring(self.client.get(reverse("network", args=[compute.id, "lab"])).content)
        dialog = page.get_element_by_id("FixedAddress")
        mac = re.compile(dialog.xpath(".//input[@name='mac']/@pattern")[0])
        name = re.compile(dialog.xpath(".//input[@name='name']/@pattern")[0])
        for value in ("52:54:00:ab:cd:ef", "52:54:00:AB:CD:EF", "0:1:0:1:2a:3b"):
            with self.subTest(mac=value):
                self.assertTrue(mac.fullmatch(value))
        for value in ("web-01", "db.lan", "vm_1"):
            with self.subTest(name=value):
                self.assertTrue(name.fullmatch(value))
        for value in ("a b", 'x"<'):
            with self.subTest(refused=value):
                self.assertFalse(name.fullmatch(value))
