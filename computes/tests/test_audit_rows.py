"""Adding, changing and deleting a compute, on the web and on the API, each write one audit row."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from logs.models import Logs
from operations import claims
from operations.models import Claim
from operations.utils import busy_message

from computes.models import Compute


class ComputeAuditRowTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("audit-admin", "audit@example.com", "pw")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()  # the login's row

    def messages(self):
        return list(Logs.objects.order_by("id").values_list("message", flat=True))

    def form_data(self, hostname):
        return {"name": "c1", "hostname": hostname, "login": "admin", "password": "", "details": "", "type": 1}

    def test_add_change_delete_write_rows(self):
        self.client.post(reverse("add_tcp_host"), {**self.form_data("192.0.2.5"), "password": "secret"})
        row = Logs.objects.get()
        self.assertEqual(
            (row.message, row.success, row.host, row.ip, row.user),
            ("Compute c1 (192.0.2.5): add", True, "c1", "127.0.0.1", "audit-admin"),
        )

        compute = Compute.objects.get()
        self.client.post(reverse("compute_update", args=[compute.id]), self.form_data("192.0.2.6"))
        self.assertEqual(self.messages()[1], "Compute c1 (192.0.2.5): change hostname")

        self.client.post(reverse("compute_delete", args=[compute.id]))
        self.assertEqual(self.messages()[2], "Compute c1 (192.0.2.6): delete")
        self.assertFalse(Compute.objects.exists())

    def test_an_edit_that_changes_nothing_writes_nothing(self):
        compute = Compute.objects.create(name="c1", hostname="192.0.2.5", login="admin", password="secret", type=1)
        self.client.post(reverse("compute_update", args=[compute.id]), self.form_data("192.0.2.5"))
        self.assertFalse(Logs.objects.exists())

    def test_a_busy_delete_writes_a_failed_row(self):
        compute = Compute.objects.create(name="c1", hostname="192.0.2.5", login="admin", password="secret", type=1)
        busy = claims.Busy(None)
        claims.admit({claims.compute_key(compute.id): Claim.SHARED}, holder="192.0.2.30:1:1")
        self.client.post(reverse("compute_delete", args=[compute.id]))
        row = Logs.objects.get()
        self.assertEqual(row.message, f"Compute c1 (192.0.2.5): delete: {busy_message(busy, self.admin)}")
        self.assertFalse(row.success)
        self.assertTrue(Compute.objects.exists())

    def test_the_api_writes_the_same_rows(self):
        data = {"name": "c1", "hostname": "192.0.2.5", "login": "admin", "password": "secret", "type": 1}
        res = self.client.post("/api/v1/computes/", data, content_type="application/json")
        self.assertEqual(res.status_code, 201)
        pk = res.json()["id"]
        res = self.client.patch(f"/api/v1/computes/{pk}/", {"hostname": "192.0.2.6"}, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        res = self.client.delete(f"/api/v1/computes/{pk}/")
        self.assertEqual(res.status_code, 204)
        self.assertEqual(
            self.messages(),
            ["Compute c1 (192.0.2.5): add", "Compute c1 (192.0.2.5): change hostname", "Compute c1 (192.0.2.6): delete"],
        )
