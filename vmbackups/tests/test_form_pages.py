"""The backup forms as a page shows them: a list's empty choice says to choose, a field's
label is not repeated in it, and a pool field offers the chosen compute's pools."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import html


class FormPageTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("fp-admin", "fp@example.com", "pw"))

    def test_a_new_target_s_form(self):
        page = html.fromstring(self.client.get(reverse("vmbackups:target_new")).content)
        self.assertEqual(page.xpath("//select[@name='compute']/option[1]/text()"), ["Choose…"])
        self.assertEqual(page.xpath("//input[@name='name']/@placeholder"), [])
        (pool,) = page.xpath("//input[@name='pool']")
        self.assertEqual(pool.get("data-pools"), reverse("vmbackups:pools", args=[0]) + "?types=dir,netfs")

    def test_a_compute_s_file_pools_are_listed_with_their_types(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from computes.models import Compute

        host = Compute.objects.create(name="fp-host", hostname="192.0.2.12", login="", password="", type=4)
        xml = lambda kind: SimpleNamespace(XMLDesc=lambda flags: f"<pool type='{kind}'/>")
        pools = {"nfs": (xml("netfs"), "/n"), "local": (xml("dir"), "/l"), "disk": (xml("fs"), "/f")}
        with patch("vmbackups.views.wvmConnect") as connect:
            connect.return_value.file_pools.return_value = pools
            listed = lambda query="": self.client.get(reverse("vmbackups:pools", args=[host.pk]) + query).json()
            self.assertEqual([p["name"] for p in listed()], ["disk", "local", "nfs"])
            self.assertEqual(listed("?types=dir,netfs"), [{"name": "local", "type": "dir"}, {"name": "nfs", "type": "netfs"}])

    def test_a_new_schedule_s_form_asks_which_vms_first(self):
        page = html.fromstring(self.client.get(reverse("vmbackups:policy_new")).content)
        self.assertEqual(page.xpath("//input[@name='scope']/@value"), ["compute", "instances", "tag"])
        self.assertEqual(page.xpath("//input[@name='scope'][@checked]/@value"), ["compute"])
        self.assertEqual(page.xpath("//*[@data-scope]/@data-scope"), ["compute", "instances", "tag"])
