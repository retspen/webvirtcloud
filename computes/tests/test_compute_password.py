"""The compute form never shows the stored password: a password left empty
on an edit keeps it, a new one replaces it."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute


class ComputePasswordTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("cp-admin", "cp@example.com", "pw"))

    def edit(self, compute, password):
        data = {"name": compute.name, "hostname": compute.hostname, "login": "admin", "password": password,
                "type": compute.type, "details": ""}
        self.client.post(reverse("compute_update", args=[compute.id]), data)
        compute.refresh_from_db()
        return compute.password

    def test_an_empty_password_keeps_the_stored_one(self):
        for conn_type in (1, 3):  # TCP, TLS
            with self.subTest(type=conn_type):
                compute = Compute.objects.create(name=f"cp{conn_type}", hostname="10.0.0.7", login="admin",
                                                 password="secret", type=conn_type)
                self.assertEqual(self.edit(compute, ""), "secret")
                self.assertEqual(self.edit(compute, "other"), "other")

    def test_a_long_password_is_kept_and_the_page_says_edit(self):
        compute = Compute.objects.create(name="cp-long", hostname="192.0.2.7", login="admin", password="", type=1)
        self.assertContains(self.client.get(reverse("compute_update", args=[compute.id])), "Edit Compute")
        self.assertEqual(self.edit(compute, "p" * 40), "p" * 40)
