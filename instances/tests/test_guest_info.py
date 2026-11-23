"""The Guest Info tab's reading: the guest's OS and its file systems, their
sizes in words for the page."""

from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from lxml import html

from computes.models import Compute
from instances.models import Instance


class GuestInfoTestCase(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="gi", hostname="192.0.2.41", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="gi-vm", uuid="00000000-0000-4000-8000-0000000000a1")
        self.client.force_login(get_user_model().objects.create_superuser("gi-admin", "gi@example.com", "pw"))
        patcher = patch.object(Instance, "proxy", new_callable=PropertyMock)
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)

    def test_each_file_system_is_told_in_words(self):
        self.proxy.osinfo.return_value = {"id": "rocky", "filesystems": [
            {"mountpoint": "/", "type": "xfs", "used": 9 * 2**30, "total": 10 * 2**30}]}
        data = self.client.get(reverse("instances:osinfo", args=[self.instance.pk])).json()
        self.assertEqual(data["filesystems"], [{"mountpoint": "/", "type": "xfs", "used": 9 * 2**30, "total": 10 * 2**30,
                                                "used_text": "9\xa0GiB", "total_text": "10\xa0GiB", "percent": 90}])

    def test_a_file_system_used_past_its_total_is_full(self):
        # a BSD guest's total leaves out the space reserved for root, which used counts
        self.proxy.osinfo.return_value = {"filesystems": [{"mountpoint": "/", "type": "ufs", "used": 104, "total": 100}]}
        data = self.client.get(reverse("instances:osinfo", args=[self.instance.pk])).json()
        self.assertEqual(data["filesystems"][0]["percent"], 100)

    def test_the_tab_has_a_hidden_table_for_them(self):
        # filled and shown by instance_page.js when the agent gives some
        table = html.fromstring(render_to_string("instances/info_tab.html")).xpath("//table[@id='osfilesystems']")[0]
        self.assertIsNotNone(table.get("hidden"))
        self.assertEqual(table.xpath(".//th/text()"), ["Mount point", "Type", "Used"])
        # in a box that scrolls a long mount point, not in a margin past the tab's edge
        self.assertIn("table-responsive", table.getparent().get("class"))
        self.assertNotIn("mx-3", table.get("class"))
        (note,) = html.fromstring(render_to_string("instances/info_tab.html")).xpath("//p[@id='osfilesystems-unread']")
        self.assertIsNotNone(note.get("hidden"))
