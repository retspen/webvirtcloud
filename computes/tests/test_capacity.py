"""What each compute has given its VMs (computes/capacity.py) and the
Computes page that shows it."""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from computes import capacity
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError
from lxml import html

GIB = 1024 ** 3


def domain(state, memory_mib, vcpus):
    info = [state, memory_mib * 1024, memory_mib * 1024, vcpus, 0]
    return SimpleNamespace(info=lambda: info)


def pool(name, capacity_gib, available_gib):
    return SimpleNamespace(name=lambda: name, info=lambda: [2, capacity_gib * GIB, 0, available_gib * GIB])


def compute(name, domains=(), pools=(), cpus=16, memory_mib=65536, down=False, pk=1):
    connection = SimpleNamespace(
        getInfo=lambda: ["x86_64", memory_mib, cpus, 2400, 1, 1, 8, 2],
        listAllDomains=lambda flags=0: list(domains),
        listAllStoragePools=lambda flags=0: list(pools),
    )
    return SimpleNamespace(id=pk, name=name, status=Exception("down") if down else True, connection=connection)


class ReadTests(unittest.TestCase):
    def setUp(self):
        capacity._reading.clear()  # a stuck read of an earlier test may not have ended yet

    def test_a_host_gives_its_vms_cpus_and_memory(self):
        c = compute("c1", [domain(1, 4096, 4), domain(1, 2048, 2), domain(5, 8192, 8)],
                    [pool("default", 500, 120), pool("iso", 100, 90)])
        result = capacity.read(c)
        self.assertEqual(result["cpus"], 16)
        self.assertEqual(result["memory"], 64 * GIB)
        self.assertEqual(result["vcpus"], {"all": 14, "running": 6})
        self.assertEqual(result["assigned"], {"all": 14 * GIB, "running": 6 * GIB})
        self.assertEqual(result["pools"], [("default", 500 * GIB, 120 * GIB), ("iso", 100 * GIB, 90 * GIB)])

    def test_a_vm_that_goes_meanwhile_is_skipped(self):
        def gone():
            raise libvirtError("Domain not found")

        c = compute("c1", [SimpleNamespace(info=gone), domain(1, 1024, 1)])
        self.assertEqual(capacity.read(c)["vcpus"], {"all": 1, "running": 1})

    def test_a_down_host_has_no_capacity(self):
        self.assertIsNone(capacity.read(compute("c1", down=True)))

    def test_hosts_are_read_together_by_the_deadline(self):
        slow = threading.Event()
        try:
            stuck = compute("c2", pk=2)
            stuck.connection.getInfo = lambda: slow.wait() and None
            started = time.monotonic()
            found = capacity.read_all([compute("c1"), stuck], deadline=0.3)
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(set(found), {1})
        finally:
            slow.set()


    def test_a_host_still_being_read_is_not_read_again(self):
        # a stuck read keeps its thread; a second page load must not add another
        slow, calls = threading.Event(), []
        try:
            stuck = compute("c2", pk=2)
            stuck.connection.getInfo = lambda: calls.append(1) or slow.wait() and None
            for _ in range(2):
                self.assertEqual(set(capacity.read_all([compute("c1"), stuck], deadline=0.2)), {1})
            self.assertEqual(len(calls), 1)
        finally:
            slow.set()


    def test_a_host_whose_read_never_started_is_read_next_time(self):
        # more hosts than threads: a read still queued at the deadline is cancelled
        slow = threading.Event()
        try:
            stuck = compute("c1")
            stuck.connection.getInfo = lambda: slow.wait() and None
            with patch.object(capacity, "MAX_WORKERS", 1):
                self.assertEqual(capacity.read_all([stuck, compute("c2", pk=2)], deadline=0.2), {})
            self.assertEqual(set(capacity.read_all([compute("c2", pk=2)], deadline=1)), {2})
        finally:
            slow.set()


class ComputesPageTests(TestCase):
    def test_the_list_shows_what_each_compute_has_given(self):
        admin = get_user_model().objects.create_superuser("cap-admin", "cap@example.com", "pw")
        self.client.force_login(admin)
        c1 = Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        Compute.objects.create(name="host-two", hostname="192.0.2.2", login="u", password="p", type=1)
        found = {c1.id: {"cpus": 16, "memory": 64 * GIB, "vcpus": {"all": 40, "running": 24},
                         "assigned": {"all": 48 * GIB, "running": 32 * GIB},
                         "pools": [("default", 500 * GIB, 120 * GIB)]}}
        with patch("computes.views.capacity.read_all", return_value=found), \
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
        # host-two answered nothing in time: one cell says so
        self.assertIn("could not be read in time", " ".join(two.text_content().split()))

    def test_the_default_pool_shows_and_the_others_open_on_a_click(self):
        admin = get_user_model().objects.create_superuser("cap-pools", "pools@example.com", "pw")
        self.client.force_login(admin)
        c1 = Compute.objects.create(name="host-one", hostname="192.0.2.1", login="u", password="p", type=1)
        pools = [("backup", 900 * GIB, 800 * GIB), ("default", 500 * GIB, 120 * GIB),
                 ("iso", 100 * GIB, 90 * GIB), ("nfs", 2000 * GIB, 1000 * GIB)]
        found = {c1.id: {"cpus": 16, "memory": 64 * GIB, "vcpus": {"all": 8, "running": 8},
                         "assigned": {"all": 8 * GIB, "running": 8 * GIB}, "pools": pools}}
        with patch("computes.views.capacity.read_all", return_value=found), \
                patch.object(Compute, "status", new=True):
            page = html.fromstring(self.client.get(reverse("computes")).content)
        (storage,) = page.xpath("//tbody/tr/td[4]")
        shown = " ".join(" ".join(storage.xpath("./div//text()")).split())
        self.assertIn("default", shown)
        self.assertNotIn("backup", shown)
        (more,) = storage.xpath(".//details")
        self.assertEqual(" ".join(more.xpath("summary")[0].text_content().split()), "3 more pools")
        self.assertEqual(more.xpath(".//div[@class='small']/text()"), ["backup", "iso", "nfs"])
