"""The secrets page never holds a secret's value: the Set value dialog only
writes a new one. Each secret shows the VMs and pools that use it, and one in
use is not offered for deletion."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from lxml import html

UUID = "0e5b1f0a-8f3e-4c1a-9d2b-5c6d7e8f9a0b"


class SecretsPageTests(TestCase):
    def page(self, usage_type="ceph", users=None):
        compute = Compute.objects.create(name="secrets-page", hostname="localhost", login="", password="", type=4)
        Instance.objects.create(compute=compute, name="db-1", uuid="00000000-0000-4000-8000-0000000000d1")
        self.client.force_login(get_user_model().objects.create_superuser("page", "page@example.com", "pw"))
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.get_secrets_info.return_value = [
                {"uuid": UUID, "usage_type": usage_type, "usage": "client.libvirt", "ephemeral": False, "private": True}]
            conn.return_value.get_users.return_value = users or {}
            response = self.client.get(reverse("virtsecrets", args=[compute.id]))
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def test_a_vtpm_secret_is_listed(self):
        self.assertEqual(self.page("vtpm").xpath("//tbody/tr/td[1]/span/text()"), ["vTPM"])

    def test_the_page_holds_no_secret_value(self):
        field = self.page().get_element_by_id("set_value")
        self.assertIsNone(field.get("value"))
        self.assertEqual(field.get("type"), "password")

    def test_a_secret_in_use_shows_its_users_and_is_not_deleted(self):
        page = self.page(users={UUID: {"vms": ["db-1", "gone-1"], "pools": ["ceph-rbd"]}})
        instance = Instance.objects.get(name="db-1")
        self.assertEqual(page.xpath("//tbody/tr/td[4]//a/@href")[0], reverse("instances:instance", args=[instance.id]))
        self.assertIn("gone-1", page.xpath("string(//tbody/tr/td[4])"))
        self.assertTrue(page.xpath("//tbody/tr/td[4]//a[contains(., 'ceph-rbd')]"))
        self.assertIsNotNone(page.xpath("//button[@name='delete']")[0].get("disabled"))

    def test_an_unused_secret_can_be_deleted(self):
        self.assertIsNone(self.page().xpath("//button[@name='delete']")[0].get("disabled"))

    def test_a_secret_without_usage_is_named_by_its_uuid(self):
        compute = Compute.objects.create(name="secrets-none", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("none", "none@example.com", "pw"))
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.get_secrets_info.return_value = [
                {"uuid": UUID, "usage_type": "none", "usage": "", "ephemeral": True, "private": False}]
            conn.return_value.get_users.return_value = {}
            page = html.fromstring(self.client.get(reverse("virtsecrets", args=[compute.id])).content)
        self.assertEqual(page.xpath("//button[@data-bs-target='#SetSecretValue']/@data-usage"), [UUID])
        self.assertEqual(page.xpath("//tbody/tr/td[1]/span/text()"), ["none"])
