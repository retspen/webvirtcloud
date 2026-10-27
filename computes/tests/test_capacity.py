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
VMS = {"running": 3, "paused": 1, "shutoff": 2, "other": 0}


class CapacityTests(TestCase):
    def setUp(self):
        self.compute = Compute(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        self.compute.status = True

    @patch("computes.models.wvmHostDetails")
    def test_a_host_tells_what_it_gave(self, details):
        details.return_value.get_capacity.return_value = {"cpus": 16, "vcpus": {"all": 24, "running": 8}}
        self.assertEqual(self.compute.capacity, {"cpus": 16, "vcpus": {"all": 24, "running": 8}, "ratio": 1.5})

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
                         "assigned": {"all": 48 * GIB, "running": 32 * GIB}, "ratio": 2.5, "vms": VMS}}
        with patch.object(Compute, "capacity", new=property(lambda c: found.get(c.id))), \
                patch.object(Compute, "status", new=True):
            page = html.fromstring(self.client.get(reverse("computes")).content)
        headers = [" ".join(th.text_content().split()) for th in page.xpath("//thead//th")]
        # no pools: measuring their space scans each pool of each host (views.host_pools)
        self.assertEqual(headers, ["Host", "vCPUs", "Memory", "Actions"])
        one, two = page.xpath("//tbody/tr")
        cells = [" ".join(td.text_content().split()) for td in one.xpath("td")]
        self.assertIn("host-one", cells[0])
        self.assertIn("2.5:1", cells[1])
        self.assertIn("40 vCPUs on 16 CPUs 24 running", cells[1])
        self.assertIn("75 % 48.0 GB / 64.0 GB", cells[2])
        self.assertIn("32.0 GB running", cells[2])
        # host-two could not be read: one cell says so
        self.assertIn("capacity could not be read", " ".join(two.text_content().split()))


class SingularTests(TestCase):
    def test_one_vcpu_on_one_cpu_is_singular(self):
        admin = get_user_model().objects.create_superuser("cap-one", "one@example.com", "pw")
        self.client.force_login(admin)
        c = Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        given = {"cpus": 1, "memory": 4 * GIB, "vcpus": {"all": 1, "running": 1},
                 "assigned": {"all": GIB, "running": GIB}, "ratio": 1.0, "vms": VMS}
        with patch.object(Compute, "capacity", new=given), patch.object(Compute, "status", new=True):
            page = html.fromstring(self.client.get(reverse("computes")).content)
            line = self.client.get(reverse("compute_capacity", args=[c.id])).content.decode()
        (cell,) = page.xpath("//tbody/tr/td[2]")
        self.assertIn("1 vCPU on 1 CPU", " ".join(cell.text_content().split()))
        self.assertEqual(" ".join(line.split()), "Given to VMs: 1 vCPU (1.0:1), 1.0 GB memory.")


class NewVmDialogLineTests(TestCase):
    """The new-VM dialog loads one line per host when it opens."""

    def setUp(self):
        admin = get_user_model().objects.create_superuser("cap-line", "line@example.com", "pw")
        self.client.force_login(admin)
        self.compute = Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)

    def line(self, given):
        with patch.object(Compute, "capacity", new=given):
            response = self.client.get(reverse("compute_capacity", args=[self.compute.id]))
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        return " ".join(response.content.decode().split())

    def test_the_line_tells_what_the_host_has_given(self):
        given = {"cpus": 16, "memory": 64 * GIB, "vcpus": {"all": 24, "running": 8},
                 "assigned": {"all": 48 * GIB, "running": 32 * GIB}, "ratio": 1.5,
                 }
        self.assertEqual(self.line(given), "Given to VMs: 24 vCPUs (1.5:1), 48.0 GB memory.")

    def test_a_host_without_pools_or_capacity_says_so(self):
        given = {"cpus": 2, "memory": 4 * GIB, "vcpus": {"all": 0, "running": 0},
                 "assigned": {"all": 0, "running": 0}, "ratio": 0}
        self.assertEqual(self.line(given), "Given to VMs: 0 vCPUs (0.0:1), 0 bytes memory.")
        self.assertEqual(self.line(None), "The capacity could not be read.")
