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
        self.assertContains(self.client.get(reverse("compute_update", args=[compute.id])), "Edit host")
        self.assertEqual(self.edit(compute, "p" * 40), "p" * 40)

    def test_the_form_says_a_secret_is_stored_and_names_the_connection(self):
        compute = Compute.objects.create(name="cp-stored", hostname="192.0.2.9", login="admin", password="secret",
                                         type=1)
        response = self.client.get(reverse("compute_update", args=[compute.id]))
        self.assertContains(response, 'placeholder="Stored, leave empty to keep"', count=1)  # the password only
        self.assertContains(response, "libvirt over TCP, with a SASL login")
        self.assertContains(response, "SASL password")
        self.assertNotContains(self.client.get(reverse("add_tcp_host")), "Stored, leave empty to keep")
        # the advanced fields fold away unless one is set
        self.assertNotContains(response, "<details class=\"border-top pt-3\" open>")
        Compute.objects.filter(pk=compute.pk).update(migration_address="192.0.2.19")
        self.assertContains(self.client.get(reverse("compute_update", args=[compute.id])),
                            "<details class=\"border-top pt-3\" open>")

    def test_the_api_keeps_the_password_when_it_is_left_empty(self):
        compute = Compute.objects.create(name="cp-api", hostname="192.0.2.8", login="admin", password="secret", type=1)
        for password in ("", None):
            with self.subTest(password=password):
                self.client.patch(f"/api/v1/computes/{compute.id}/", {"password": password}, content_type="application/json")
                compute.refresh_from_db()
                self.assertEqual(compute.password, "secret")
        self.assertEqual(self.client.get("/api/v1/computes/999999/archs/").status_code, 404)
