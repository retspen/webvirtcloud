"""A network's DHCP leases on its page: each with the VM whose card has its
MAC, a mark when it is a fixed address, and a "Make fixed" button that fills
in the fixed address dialog, by MAC for IPv4 and by DUID for IPv6. Leases
that cannot be read leave the rest of the page. Runs on a private libvirt
test driver, which has no leases: they are given."""

import tempfile
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from vrtManager.tests.driver import without_inactive_flag
from vrtManager.tests.fakes import DUID, NAT_NETWORK_NODE, lease


class LeasesCardTests(TestCase):
    def setUp(self):
        node = tempfile.NamedTemporaryFile("w", suffix=".xml")
        self.addCleanup(node.close)
        node.write(NAT_NETWORK_NODE)
        node.flush()
        self.conn = libvirt.open(f"test://{node.name}")
        self.addCleanup(self.conn.close)
        patcher = patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)
        without_inactive_flag(self)
        self.compute = Compute.objects.create(name="nl", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("nl", "nl@example.com", "pw"))
        web = self.conn.lookupByName("web")
        self.vm = Instance.objects.create(compute=self.compute, name="web", uuid=web.UUIDString())
        self.mac = html.fromstring(web.XMLDesc(0)).xpath("string(//interface/mac/@address)")

    def rows(self, leases):
        with patch.object(libvirt.virNetwork, "DHCPLeases", return_value=leases, create=True):
            response = self.client.get(reverse("network", args=[self.compute.id, "lab"]))
        self.assertEqual(response.status_code, 200)
        page = html.fromstring(response.content)
        card = page.xpath("//div[@class='card mb-3'][div[@class='card-header'][starts-with(normalize-space(), 'DHCP leases')]]")[0]
        return card, card.xpath(".//tbody/tr")

    def test_each_lease_with_its_vm_and_whether_it_is_fixed(self):
        _, (by_vm, fixed, stale, ipv6) = self.rows([
            lease("192.0.2.15", self.mac.upper(), hostname="web-guest"),
            lease("192.0.2.31", "52:54:00:00:00:31"),
            lease("198.51.100.5", "52:54:00:00:00:99"),  # a removed VM's, outside the network's subnets
            lease("2001:db8:1::40", family=1, clientid=DUID),
        ])
        self.assertEqual(by_vm.xpath("td[4]/a/@href"), [reverse("instances:instance", args=[self.vm.id])])
        button = by_vm.xpath(".//button[@data-bs-target='#FixedAddress']")[0]
        self.assertEqual((button.get("data-ip-index"), button.get("data-address"), button.get("data-mac"), button.get("data-name")),
                         ("0", "192.0.2.15", self.mac.lower(), "web-guest"))
        self.assertIn("Fixed", fixed.xpath("string(td[1])"))
        self.assertFalse(fixed.xpath(".//button"))
        self.assertEqual((stale.xpath("normalize-space(td[4])"), stale.xpath(".//button")), ("–", []))
        # an IPv6 fixed address is known by the client's DUID, not a MAC
        button = ipv6.xpath(".//button")[0]
        self.assertEqual((button.get("data-ip-index"), button.get("data-mac"), button.get("data-name")), ("1", DUID, ""))

    def test_an_ipv6_lease_is_known_by_its_duid_and_its_address_however_written(self):
        _, (fixed, other) = self.rows([
            lease("2001:db8:1:0:0:0:0:31", family=1, clientid="0:1:0:1"),  # the fixed 2001:db8:1::31
            lease("2001:db8:1::41", "52:54:00:00:00:41", family=1, clientid=DUID),
        ])
        self.assertEqual((fixed.xpath("normalize-space(td[1])"), fixed.xpath(".//button")), ("2001:db8:1::31 Fixed", []))
        self.assertEqual(other.xpath(".//button/@data-mac"), [DUID])

    def test_a_vm_the_panel_does_not_know_is_named_not_linked(self):
        self.vm.delete()
        _, (row,) = self.rows([lease("192.0.2.15", self.mac)])
        self.assertEqual((row.xpath("normalize-space(td[4])"), row.xpath("td[4]/a")), ("web", []))
        # without a host name, the fixed address takes the VM's name
        self.assertEqual(row.xpath(".//button/@data-name"), ["web"])

    def test_leases_that_cannot_be_read_leave_the_page(self):
        with patch.object(libvirt.virNetwork, "DHCPLeases", side_effect=libvirt.libvirtError("status file unreadable"),
                          create=True):
            response = self.client.get(reverse("network", args=[self.compute.id, "lab"]))
        page = html.fromstring(response.content)
        self.assertIn("The leases could not be read: status file unreadable", page.text_content())
        self.assertTrue(page.xpath("//tbody[@class='searchable']/tr"), "the fixed addresses are still shown")
