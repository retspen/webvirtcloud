"""App setting and theme changes write rows on the Logs page."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse

from appsettings.models import AppSettings
from logs.models import Logs


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success", "host"))


class SettingRowTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("audit-admin", "audit@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row
        self.url = reverse("appsettings")

    def test_setting_and_theme_rows(self):
        name = AppSettings.objects.get(key="LOGS_PER_PAGE").name
        self.client.post(self.url, {"LOGS_PER_PAGE": "50"})
        self.client.post(self.url, {"LOGS_PER_PAGE": "50"})  # no change
        before = AppSettings.objects.get(key="WORKER_CONCURRENCY").value
        self.client.post(self.url, {"WORKER_CONCURRENCY": "0"})  # out of bounds
        self.assertEqual(AppSettings.objects.get(key="WORKER_CONCURRENCY").value, before)
        theme = "cerulean" if AppSettings.objects.get(key="BOOTSTRAP_THEME").value != "cerulean" else "brite"
        self.client.post(self.url, {"BOOTSTRAP_THEME": theme})
        self.client.post(self.url, {"BOOTSTRAP_THEME": theme})  # no change
        self.assertEqual(rows(), [
            (f"Setting {name}: change to 50", True, "-"),
            (f"Setting Theme: change to {theme}", True, "-"),
        ])

    def test_a_failing_save_is_a_failed_row(self):
        name = AppSettings.objects.get(key="LOGS_PER_PAGE").name
        with patch.object(AppSettings, "save", side_effect=DatabaseError("disk full")):
            response = self.client.post(self.url, {"LOGS_PER_PAGE": "50"}, follow=True)
        self.assertIn("error", [m.level_tag for m in response.context["messages"]])
        self.assertEqual(rows(), [(f"Setting {name}: change to 50: DatabaseError", False, "-")])
