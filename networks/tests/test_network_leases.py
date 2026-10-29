"""A network's DHCP leases on its page: each with the VM whose card has its
MAC, a mark when it is a fixed address, and a "Make fixed" button that fills
in the fixed address dialog, by MAC for IPv4 and by DUID for IPv6. Leases
that cannot be read leave the rest of the page. Runs on a private libvirt
test driver, which has no leases: they are given."""

import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html
from networks.tests.driver import without_inactive_flag
from networks.tests.test_network_pages import NODE
from vrtManager.network import wvmNetwork

DUID = "00:01:00:01:2e:8b:3c:41:52:54:00:00:00:40"


def lease(ip, mac=None, expiry=1793265489, hostname=None, clientid=None, family=0):
    return {"iface": "virbr9", "expirytime": expiry, "type": family, "mac": mac, "ipaddr": ip, "prefix": 24,
            "hostname": hostname, "clientid": clientid, "iaid": None}


class LeasesTests(SimpleTestCase):
    def network(self, leases, active=True):
        net = wvmNetwork.__new__(wvmNetwork)
        net.net = MagicMock(**{"isActive.return_value": active, "DHCPLeases.return_value": leases})
        return net

    def test_leases_by_address_ipv4_first(self):
        net = self.network([lease("2001:db8:1::40", family=1, clientid=DUID, expiry=0),
                            lease("192.0.2.100", "52:54:00:AA:00:01", hostname="db"),
                            lease("192.0.2.9", "52:54:00:aa:00:02")])
        ipv4_9, ipv4_100, ipv6 = net.get_leases()
        self.assertEqual([str(ipv4_9["ip"]), str(ipv4_100["ip"]), str(ipv6["ip"])], ["192.0.2.9", "192.0.2.100", "2001:db8:1::40"])
        self.assertEqual((ipv4_100["mac"], ipv4_100["hostname"], ipv4_100["expires"]),
                         ("52:54:00:aa:00:01", "db", datetime.fromtimestamp(1793265489, timezone.utc)))
        # an IPv6 lease: no MAC, its client's DUID; one that never ends
        self.assertEqual((ipv6["mac"], ipv6["client_id"], ipv6["expires"]), ("", DUID, None))

    def test_a_network_that_does_not_run_has_none(self):
        net = self.network([lease("192.0.2.9")], active=False)
        self.assertEqual(net.get_leases(), [])
        net.net.DHCPLeases.assert_not_called()


class LeasesCardTests(TestCase):
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
