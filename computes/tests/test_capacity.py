"""What each compute has given its VMs (Compute.capacity) and the Computes
page that shows it."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError
from lxml import html

GIB = 1024 ** 3


def pool(name, size_gib, free_gib, status=1):
    return {"name": name, "status": status, "size": size_gib * GIB, "free": free_gib * GIB}


class CapacityTests(TestCase):
    def setUp(self):
        self.compute = Compute(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        self.compute.status = True

    @patch("computes.models.wvmStorages")
    @patch("computes.models.wvmHostDetails")
    def test_a_host_tells_what_it_gave_and_its_active_pools(self, details, storages):
        details.return_value.get_capacity.return_value = {"cpus": 16}
        storages.return_value.get_storages_info.return_value = [pool("default", 500, 120), pool("off", 10, 0, status=0)]
        self.assertEqual(self.compute.capacity, {"cpus": 16, "pools": [pool("default", 500, 120)]})

    @patch("computes.models.wvmHostDetails")
    def test_a_host_whose_read_fails_has_no_capacity(self, details):
        # a VM that goes while the host is read, for one
        details.return_value.get_capacity.side_effect = libvirtError("Domain not found")
        self.assertIsNone(self.compute.capacity)

    @patch("computes.models.wvmHostDetails")
    def test_a_down_host_is_not_read(self, details):
        self.compute.status = False
        self.assertIsNone(self.compute.capacity)
        details.assert_not_called()


class ComputesPageTests(TestCase):
    def test_the_list_shows_what_each_compute_has_given(self):
        admin = get_user_model().objects.create_superuser("cap-admin", "cap@example.com", "pw")
        self.client.force_login(admin)
        c1 = Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        Compute.objects.create(name="host-two", hostname="192.0.2.2", login="u", password="p", type=1)
        found = {c1.id: {"cpus": 16, "memory": 64 * GIB, "vcpus": {"all": 40, "running": 24},
                         "assigned": {"all": 48 * GIB, "running": 32 * GIB},
                         "pools": [pool("default", 500, 120)]}}
        with patch.object(Compute, "capacity", new=property(lambda c: found.get(c.id))), \
                patch.object(Compute, "status", new=True):
            page = html.fromstring(self.client.get(reverse("computes")).content)
        headers = [" ".join(th.text_content().split()) for th in page.xpath("//thead//th")]
        self.assertEqual(headers, ["Host", "vCPUs", "Memory", "Storage", "Actions"])
        one, two = page.xpath("//tbody/tr")
        cells = [" ".join(td.text_content().split()) for td in one.xpath("td")]
        self.assertIn("host-one", cells[0])
        self.assertIn("2.5:1", cells[1])
        self.assertIn("40 vCPUs on 16 CPUs 24 running", cells[1])
        self.assertIn("48.0 GB given of 64.0 GB", cells[2])
        self.assertIn("32.0 GB of it running", cells[2])
        self.assertIn("120.0 GB free of 500.0 GB", cells[3])
        # host-two could not be read: one cell says so
        self.assertIn("capacity could not be read", " ".join(two.text_content().split()))

    def test_the_default_pool_shows_and_the_others_open_on_a_click(self):
        admin = get_user_model().objects.create_superuser("cap-pools", "pools@example.com", "pw")
        self.client.force_login(admin)
        Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        # libvirt lists the pools in no order
        pools = [pool("nfs", 2000, 1000), pool("default", 500, 120), pool("iso", 100, 90), pool("backup", 900, 800)]
        given = {"cpus": 16, "memory": 64 * GIB, "vcpus": {"all": 8, "running": 8},
                 "assigned": {"all": 8 * GIB, "running": 8 * GIB}, "pools": pools}
        with patch.object(Compute, "capacity", new=given), patch.object(Compute, "status", new=True):
            page = html.fromstring(self.client.get(reverse("computes")).content)
        (storage,) = page.xpath("//tbody/tr/td[4]")
        shown = " ".join(" ".join(storage.xpath("./div//text()")).split())
        self.assertIn("default", shown)
        self.assertNotIn("backup", shown)
        (more,) = storage.xpath(".//details")
        self.assertEqual(" ".join(more.xpath("summary")[0].text_content().split()), "3 more pools")
        self.assertEqual(more.xpath(".//div[@class='small']/text()"), ["backup", "iso", "nfs"])
