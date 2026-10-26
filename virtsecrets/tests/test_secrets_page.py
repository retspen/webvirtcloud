"""The secrets page never holds a secret's value: the edit dialog only
writes a new one."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import VIR_SECRET_USAGE_TYPE_CEPH, VIR_SECRET_USAGE_TYPE_VTPM
from lxml import html


class SecretsPageTests(TestCase):
    def page(self, usage_type):
        compute = Compute.objects.create(name="secrets-page", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("page", "page@example.com", "pw"))
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.get_secrets.return_value = ["0e5b1f0a-8f3e-4c1a-9d2b-5c6d7e8f9a0b"]
            secret = conn.return_value.get_secret.return_value
            secret.usageID.return_value = "client.libvirt"
            secret.UUIDString.return_value = "0e5b1f0a-8f3e-4c1a-9d2b-5c6d7e8f9a0b"
            secret.usageType.return_value = usage_type
            secret.value.return_value = b"cephx key"
            conn.return_value.get_secret_value.return_value = "Y2VwaHgga2V5"
            response = self.client.get(reverse("virtsecrets", args=[compute.id]))
        self.assertEqual(response.status_code, 200)
        return response

    def test_a_vtpm_secret_is_listed(self):
        self.assertContains(self.page(VIR_SECRET_USAGE_TYPE_VTPM), "vtpm")

    def test_the_page_holds_no_secret_value(self):
        response = self.page(VIR_SECRET_USAGE_TYPE_CEPH)
        self.assertFalse(b"Y2VwaHgga2V5" in response.content, "the secret's value is on the page")
        field = html.fromstring(response.content).get_element_by_id("secret_value_0e5b1f0a-8f3e-4c1a-9d2b-5c6d7e8f9a0b")
        self.assertIsNone(field.get("value"))
        self.assertEqual(field.get("type"), "password")
