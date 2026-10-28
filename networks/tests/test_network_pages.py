"""The network pages: a card per network with its mode, device and
addresses (none of its own for a bridge); a network's page with an address
card per <ip>, its fixed addresses in one table, the VMs on it, bandwidth
limits only where libvirt sets them; the new network dialog opens again
with what was entered and why. Runs on a private libvirt test driver."""

import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from networks.tests.driver import without_inactive_flag

NODE = """<node>
  <network><name>lab</name><forward mode='nat'/><bridge name='virbr9'/>
    <ip address='192.0.2.1' netmask='255.255.255.0'><dhcp><range start='192.0.2.10' end='192.0.2.20'/>
      <host mac='52:54:00:00:00:31' name='web' ip='192.0.2.31'/></dhcp></ip>
    <ip family='ipv6' address='2001:db8:1::1' prefix='64'><dhcp><host id='0:1:0:1' ip='2001:db8:1::31'/></dhcp></ip>
  </network>
  <network><name>lan</name><forward mode='bridge'/><bridge name='br0'/></network>
  <network><name>direct</name><forward mode='bridge'><interface dev='eth0'/></forward></network>
  <domain type='test'><name>web</name><memory>1024</memory><os><type>hvm</type></os>
    <devices><interface type='network'><source network='lab'/></interface></devices></domain>
</node>"""


class NetworkPageTests(TestCase):
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
        self.compute = Compute.objects.create(name="np", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("np", "np@example.com", "pw"))

    def page(self, response):
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def text(self, element):
        return " ".join(" ".join(element.itertext()).split())

    def test_the_list_tells_each_network_mode_and_addresses(self):
        page = self.page(self.client.get(reverse("networks", args=[self.compute.id])))
        cards = {card.xpath("string(.//div[contains(@class,'card-header')]//a)"): self.text(card)
                 for card in page.xpath("//div[@class='card h-100']")}
        self.assertIn("Type NAT Device virbr9 IPv4 192.0.2.0/24 DHCP 192.0.2.10 – 192.0.2.20 "
                      "IPv6 2001:db8:1::/64 DHCP: fixed addresses only", cards["lab"])
        self.assertIn("Type Bridge Device br0 Addresses from the outside network", cards["lan"])
        self.assertIn("Type Macvtap Device eth0 Addresses from the outside network", cards["direct"])

    def test_a_network_page(self):
        vm = Instance.objects.create(compute=self.compute, name="web", uuid=self.conn.lookupByName("web").UUIDString())
        page = self.page(self.client.get(reverse("network", args=[self.compute.id, "lab"])))
        # an address card per <ip>, the fixed addresses of both in one table
        self.assertEqual(len(page.xpath("//button[@data-bs-target='#DhcpRange']")), 1)
        rows = [self.text(row) for row in page.xpath("//tbody[@class='searchable']/tr")]
        self.assertEqual([row.split(" Edit")[0] for row in rows], ["192.0.2.31 52:54:00:00:00:31 web", "2001:db8:1::31 0:1:0:1 –"])
        self.assertEqual(page.xpath("//tbody/tr/td//input[@name='ip_index']/@value"), ["0", "1"])
        # the VMs on it, linked
        self.assertEqual(page.xpath(f"//a[@href='{reverse('instances:instance', args=[vm.id])}']/text()"), ["web"])
        self.assertTrue(page.xpath("//div[@id='QosLimit']"))

    def test_a_bridge_or_macvtap_network_has_no_addresses_of_libvirt(self):
        for name, qos in (("lan", True), ("direct", False)):  # libvirt limits a host bridge, not macvtap
            with self.subTest(name=name):
                page = self.page(self.client.get(reverse("network", args=[self.compute.id, name])))
                self.assertIn("take their addresses from the outside network", self.text(page))
                self.assertFalse(page.xpath("//div[@id='FixedAddress']"))
                self.assertEqual(bool(page.xpath("//div[@id='QosLimit']")), qos)

    def test_a_vm_undefined_meanwhile_is_left_out(self):
        error = libvirt.libvirtError("Domain not found")
        error.get_error_code = lambda: libvirt.VIR_ERR_NO_DOMAIN
        with patch.object(libvirt.virDomain, "isActive", side_effect=error):
            page = self.page(self.client.get(reverse("network", args=[self.compute.id, "lab"])))
        self.assertIn("No VM is defined on this network.", self.text(page))

    def test_an_action_does_not_read_the_page(self):
        # every action redirects: the VMs on the network are not scanned for it
        with patch("vrtManager.network.wvmNetwork.get_vms") as get_vms:
            response = self.client.post(reverse("network", args=[self.compute.id, "lab"]), {"set_autostart": ""})
        self.assertEqual(response.status_code, 302)
        get_vms.assert_not_called()

    def test_a_refused_network_opens_the_dialog_again(self):
        page = self.page(self.client.post(reverse("networks", args=[self.compute.id]), {
            "create": "", "name": "lab2", "forward": "route", "subnet": "192.0.2.0/25"}))
        dialog = page.get_element_by_id("AddNetPool")
        self.assertIsNotNone(dialog.get("data-open"))
        self.assertEqual(page.xpath("//input[@name='forward'][@checked]/@value"), ["route"])
        self.assertEqual(page.get_element_by_id("net_subnet").get("aria-invalid"), "true")
        self.assertIn("Network lab has 192.0.2.0/24", page.get_element_by_id("net_subnet_error").text_content())
