"""The compute forms: each saves its own kind of compute, keeps a password
as typed, and tells when the host saved cannot be reached."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from computes.tests.fakes import no_host_answers


class ComputeFormTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("cf-admin", "cf@example.com", "pw"))
        no_host_answers(self)

    def add(self, **data):
        return self.client.post(reverse("add_tcp_host"), {"name": "kvm1", "hostname": "192.0.2.1", "login": "wvc",
                                                          "password": "pw", "details": "", **data}, follow=True)

    def test_a_posted_kind_is_not_taken(self):
        self.add(type=99)
        compute = Compute.objects.get(name="kvm1")
        self.assertEqual(compute.type, 1)
        self.assertEqual(self.client.get(reverse("compute_update", args=[compute.id])).status_code, 200)

    def test_a_password_keeps_its_spaces(self):
        self.add(password=" pass phrase ")
        self.assertEqual(Compute.objects.get(name="kvm1").password, " pass phrase ")
        compute = Compute.objects.get(name="kvm1")
        self.client.patch(f"/api/v1/computes/{compute.id}/", {"password": " other "}, content_type="application/json")
        compute.refresh_from_db()
        self.assertEqual(compute.password, " other ")

    def test_a_host_that_does_not_answer_is_saved_with_a_warning(self):
        response = self.add()
        self.assertTrue(Compute.objects.filter(name="kvm1").exists())
        self.assertContains(response, "The host was saved, but the panel cannot connect to it: unreachable")
