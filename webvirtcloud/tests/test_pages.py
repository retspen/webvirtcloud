"""Every HTML page a superuser can open, rendered on libvirt's test driver."""

from collections import Counter
from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse
from instances.models import Flavor, Instance
from lxml import html


def named_urls(patterns, prefix="", keys=()):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from named_urls(p.url_patterns, f"{prefix}{p.namespace}:" if p.namespace else prefix,
                                  keys + tuple(p.pattern.regex.groupindex))
        elif isinstance(p, URLPattern) and p.name:
            yield prefix + p.name, keys + tuple(p.pattern.regex.groupindex)


class PageTests(TestCase):
    def pages(self):
        """(URL name, parsed page) for every HTML page; asserts the main ones are among them."""
        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        compute = Compute.objects.create(name="testdrv", hostname="localhost", login="", password="", type=4)
        vm = Instance.objects.create(compute=compute, name="test", uuid=conn.lookupByName("test").UUIDString())
        Flavor.objects.create(label="second", memory=512, vcpu=1, disk=10)  # the flavor modals repeat per flavor
        self.client.force_login(get_user_model().objects.create_superuser("ids", "ids@example.com", "pw"))
        self.client.raise_request_exception = False
        values = {"pk": vm.id, "compute_id": compute.id, "pool": "default-pool", "arch": "i686", "machine": "pc"}
        checked = []
        with patch("vrtManager.connection.connection_manager.get_connection", return_value=conn), \
             patch("vrtManager.connection.wvmConnect.get_machine_types", return_value=["pc"]), \
             patch("vrtManager.connection.wvmConnect.get_nwfilters", return_value=[]), \
             patch("vrtManager.connection.wvmConnect.get_cpu_modes", return_value=["host-model"]), \
             patch.object(libvirt.virConnect, "getMemoryStats", return_value={"total": 8 << 20, "free": 4 << 20, "buffers": 0, "cached": 0}), \
             patch.object(libvirt.virConnect, "getCPUStats", return_value={"kernel": 1, "idle": 1, "user": 1, "iowait": 0}):
            for name, keys in named_urls(get_resolver().url_patterns):
                try:
                    url = reverse(name, kwargs={k: values.get(k, 1) for k in keys})
                except NoReverseMatch:
                    continue
                response = self.client.get(url)
                if response.status_code != 200 or not response["Content-Type"].startswith("text/html"):
                    continue
                checked.append(name)
                yield name, html.fromstring(response.content)
            # its pool key names a network, not the storage pool above
            response = self.client.get(reverse("network", kwargs={"compute_id": compute.id, "pool": "default"}))
            self.assertEqual(response.status_code, 200)
            checked.append("network")
            yield "network", html.fromstring(response.content)
        self.assertTrue({"index", "overview", "instances:instance", "nwfilter"} <= set(checked), checked)
        self.assertIn("instances:create_instance", checked)

    def test_no_page_repeats_an_id(self):
        # a repeated ID makes getElementById, labels and Bootstrap targets reach the first one only
        for name, page in self.pages():
            ids = Counter(page.xpath("//@id"))
            with self.subTest(page=name):
                self.assertEqual({i: n for i, n in ids.items() if n > 1}, {})

    def test_every_table_scrolls_in_its_own_box(self):
        # a wide table scrolls inside .table-responsive instead of widening the page on a phone
        for name, page in self.pages():
            bare = [t.get("class") for t in page.xpath("//table[not(parent::div[contains(@class, 'table-responsive')])]")]
            with self.subTest(page=name):
                self.assertEqual(bare, [])
