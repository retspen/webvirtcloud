"""The host overview page: a host the panel reaches, one it cannot reach,
and one whose details cannot be read."""

from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError
from lxml import html

from computes.models import Compute

GIB = 1024 ** 3
GIVEN = {"cpus": 8, "memory": 32 * GIB, "vcpus": {"all": 12, "running": 6},
         "assigned": {"all": 24 * GIB, "running": 12 * GIB}, "ratio": 1.5,
         "vms": {"running": 3, "paused": 1, "shutoff": 2, "other": 0}}


def pool(name, size_gib, free_gib, status=1):
    return {"name": name, "status": status, "size": size_gib * GIB, "free": free_gib * GIB,
            "used_percent": (size_gib - free_gib) * 100 / size_gib}


def text(page, xpath):
    return " ".join(" ".join(page.xpath(xpath)[0].itertext()).split())


class OverviewTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("ov-admin", "ov@example.com", "pw"))
        self.compute = Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p",
                                              type=1, details="rack 4")
        self.url = reverse("overview", args=[self.compute.id])

    def page(self, connected=True, given=GIVEN, pools=(pool("default", 500, 120),)):
        with patch("computes.views.wvmStorages") as storages, \
                patch.object(Compute, "status", new_callable=PropertyMock, return_value=connected), \
                patch.object(Compute, "connection_error", new_callable=PropertyMock,
                             return_value="Connection Failed: 192.0.2.1 did not answer within 5 s"), \
                patch.object(Compute, "capacity", new=given and {**given}):
            storages.return_value.get_storages_info.return_value = [dict(p) for p in pools]
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    @patch("computes.views.wvmHostDetails")
    def test_a_host_shows_its_vms_capacity_hardware_and_software(self, details):
        conn = details.return_value
        conn.get_node_info.return_value = ("wvc-host", "x86_64", 32 * GIB, 8, "Xeon", "qemu+tcp://192.0.2.1/system")
        conn.get_cpu_topology.return_value = {"nodes": 2, "sockets": 2, "cores": 4, "mhz": 2400, "cpus": 8}
        conn.wvm.getType.return_value = "QEMU"
        conn.get_version.return_value = "10.1.0"
        conn.get_lib_version.return_value = "11.10.0"
        conn.get_emulator.return_value = "/usr/libexec/qemu-kvm"
        conn.get_hypervisors_domain_types.return_value = {"i686": ["kvm", "qemu"], "x86_64": ["kvm", "qemu"]}
        page = self.page()
        self.assertIn("Connected", text(page, "//div[@id='host_status']"))
        self.assertIn("rack 4", text(page, "//div[@id='host_status']"))
        cards = [" ".join(" ".join(card.itertext()).split()) for card in page.xpath("//div[@class='card h-100']")]
        self.assertIn("VMs 6 3 running, 2 shut off, 1 paused Instances →", cards)
        self.assertTrue(any(card.startswith("vCPUs 1.5:1 12 vCPUs on 8 CPUs 6 running") for card in cards), cards)
        self.assertTrue(any(card.startswith("Memory 75 % 24.0 GB / 32.0 GB") for card in cards), cards)
        self.assertTrue(any("120.0 GB free of 500.0 GB" in card for card in cards), cards)
        hardware = text(page, "//div[@class='card-header'][normalize-space()='Hardware']/..")
        self.assertIn("Processor Xeon Architecture x86_64 Logical CPUs 8 Physical cores 4 Sockets 2 NUMA nodes 2 "
                      "Clock 2.4 GHz Memory 32.0 GB", hardware)
        software = text(page, "//div[@class='card-header'][normalize-space()='Software and connection']/..")
        self.assertIn("QEMU 10.1.0 libvirt 11.10.0", software)
        self.assertIn("x86_64 kvm · qemu", software)
        self.assertTrue(page.xpath("//canvas[@id='cpuChart']"))

    @patch("computes.views.wvmHostDetails")
    def test_the_default_pool_shows_and_the_others_open_on_a_click(self, details):
        details.return_value.get_node_info.return_value = ("h", "x86_64", GIB, 2, None, "qemu+tcp://192.0.2.1/system")
        details.return_value.get_lib_version.side_effect = libvirtError("details are not this test's")
        pools = [pool("nfs", 2000, 1000), pool("off", 10, 0, status=0), pool("default", 500, 120),
                 pool("backup", 900, 800), pool("iso", 100, 90)]
        page = self.page(pools=pools)
        storage = page.xpath("//div[@class='card-header'][normalize-space()='Storage']/..")[0]
        self.assertIn("default 120.0 GB free of 500.0 GB", " ".join(" ".join(storage.xpath("./div/div//text()")).split()))
        (more,) = storage.xpath(".//details")
        self.assertEqual(" ".join(more.xpath("summary")[0].text_content().split()), "3 more pools")
        # active pools only, by name after the default one
        self.assertEqual(more.xpath(".//div[@class='small']/text()"), ["backup", "iso", "nfs"])

    @patch("computes.views.wvmHostDetails")
    def test_pools_that_cannot_be_read_leave_the_rest(self, details):
        details.return_value.get_node_info.return_value = ("h", "x86_64", GIB, 2, None, "qemu+tcp://192.0.2.1/system")
        with patch("computes.views.host_pools", return_value=None):
            page = self.page()
        self.assertIn("The storage pools could not be read.", text(page, "//div[@class='card-header'][normalize-space()='Storage']/.."))
        self.assertTrue(page.xpath("//div[@class='card-header'][normalize-space()='VMs']"))

    @patch("computes.views.wvmHostDetails")
    def test_a_host_the_panel_cannot_reach_keeps_its_page_with_the_reason(self, details):
        page = self.page(connected=False, given=None)
        details.assert_not_called()
        self.assertIn("Not connected", text(page, "//div[@id='host_status']"))
        self.assertIn("did not answer within 5 s", text(page, "//div[@role='alert']"))
        # the way back: its sections, its connection and its removal
        self.assertTrue(page.xpath("//nav[@aria-label='Host sections']"))
        self.assertTrue(page.xpath(f"//a[@href='{reverse('compute_update', args=[self.compute.id])}']"))
        self.assertTrue(page.xpath(f"//a[@href='{reverse('compute_delete', args=[self.compute.id])}']"))
        self.assertFalse(page.xpath("//canvas"))

    @patch("computes.views.wvmHostDetails")
    def test_details_that_cannot_be_read_leave_the_capacity_and_the_load(self, details):
        details.return_value.get_node_info.return_value = ("h", "x86_64", GIB, 2, None, "qemu+tcp://192.0.2.1/system")
        details.return_value.get_lib_version.side_effect = libvirtError("cannot read the version")
        page = self.page()
        self.assertIn("cannot read the version", text(page, "//div[@role='alert']"))
        self.assertTrue(page.xpath("//div[@class='card-header'][normalize-space()='VMs']"))
        # the load is read on its own, by the charts
        self.assertTrue(page.xpath("//canvas[@id='cpuChart']"))
        self.assertFalse(page.xpath("//div[@class='card-header'][normalize-space()='Hardware']"))

    def test_the_list_links_the_overview_of_a_host_it_cannot_reach(self):
        with patch.object(Compute, "status", new_callable=PropertyMock, return_value=False):
            page = html.fromstring(self.client.get(reverse("computes")).content)
        # its name and its menu's Overview
        self.assertEqual(len(page.xpath(f"//tbody//a[@href='{self.url}']")), 2)
