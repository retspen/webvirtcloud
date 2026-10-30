"""The Stats tab: a chart for the CPU, the memory and each NIC and disk, and
the VM's log rows for superusers only, whose log view is the only one."""

from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from lxml import html

UUID = "abcdabcd-0000-0000-0000-000000000000"


def tab(status=1, superuser=True):
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(is_superuser=superuser)
    instance = SimpleNamespace(
        id=1, uuid=UUID, status=status,
        networks=[{"mac": "52:54:00:00:00:01"}], disks=[{"dev": "vda"}, {"dev": "vdb"}],
    )
    return html.fromstring(render_to_string("instances/stats_tab.html", {"instance": instance}, request))


class StatsTabTests(SimpleTestCase):
    def test_every_device_has_a_chart_and_a_reading(self):
        doc = tab()
        for name in ("cpu", "mem", "net52:54:00:00:00:01", "blkvda", "blkvdb"):
            with self.subTest(name=name):
                self.assertTrue(doc.xpath(f"//canvas[@id='{name}Chart']"))
                self.assertTrue(doc.xpath(f"//*[@id='{name}Now']"))
        self.assertIn("52:54:00:00:00:01", doc.text_content())

    def test_only_a_superuser_gets_the_logs(self):
        for superuser in (True, False):
            with self.subTest(superuser=superuser):
                doc = tab(superuser=superuser)
                self.assertEqual(bool(doc.xpath("//button[@data-bs-target='#logs']")), superuser)
                self.assertEqual(bool(doc.xpath("//table[@id='logs_table']")), superuser)

    def test_the_logs_link_to_all_of_the_vm_s_rows(self):
        self.assertEqual(tab().xpath("//a[text()=\"All of this VM's logs\"]/@href"), [f"/admin/logs/?q={UUID}"])

    def test_a_vm_that_is_not_running_says_nothing_is_measured(self):
        for status, measured in ((1, True), (3, False), (5, False)):
            with self.subTest(status=status):
                text = tab(status=status).text_content()
                self.assertEqual("Updates every 5 seconds." in text, measured)
                self.assertEqual("nothing is measured" in text, not measured)
