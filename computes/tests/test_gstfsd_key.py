"""The gstfsd key of a compute, like its password: never shown, kept when
left empty on an edit, and only 64 hexadecimal characters."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute

KEY, OTHER = "5e" * 32, "a1" * 32


class GstfsdKeyTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("gk-admin", "gk@example.com", "pw"))

    def edit(self, compute, key):
        data = {"name": compute.name, "hostname": compute.hostname, "login": "admin", "password": "",
                "type": compute.type, "details": "", "gstfsd_key": key}
        self.client.post(reverse("compute_update", args=[compute.id]), data)
        compute.refresh_from_db()
        return compute.gstfsd_key

    def test_every_kind_of_compute_takes_it_and_keeps_it(self):
        for conn_type, hostname in ((1, "192.0.2.10"), (2, "192.0.2.11"), (3, "192.0.2.12"), (4, "localhost")):
            with self.subTest(type=conn_type):
                compute = Compute.objects.create(name=f"gk{conn_type}", hostname=hostname, login="admin", type=conn_type)
                self.assertEqual(self.edit(compute, KEY), KEY)
                self.assertEqual(self.edit(compute, ""), KEY)
                self.assertEqual(self.edit(compute, OTHER), OTHER)
                page = self.client.get(reverse("compute_update", args=[compute.id])).content.decode()
                self.assertIn('name="gstfsd_key"', page)
                self.assertNotIn(OTHER, page)

    def test_a_key_that_is_not_64_hexadecimal_characters_is_refused(self):
        compute = Compute.objects.create(name="gk-bad", hostname="192.0.2.13", login="admin", type=1, gstfsd_key=KEY)
        for bad in ("5E" * 32, "5e" * 31, "zz" * 32):
            with self.subTest(key=bad):
                self.assertEqual(self.edit(compute, bad), KEY)

    def test_the_api_takes_it_but_never_shows_it(self):
        compute = Compute.objects.create(name="gk-api", hostname="192.0.2.14", login="admin", type=1)
        url = f"/api/v1/computes/{compute.id}/"
        self.client.patch(url, {"gstfsd_key": KEY}, content_type="application/json")
        self.client.patch(url, {"gstfsd_key": ""}, content_type="application/json")
        self.assertEqual(self.client.patch(url, {"gstfsd_key": "x"}, content_type="application/json").status_code, 400)
        compute.refresh_from_db()
        self.assertEqual(compute.gstfsd_key, KEY)
        self.assertNotIn("gstfsd_key", self.client.get(url).json())
