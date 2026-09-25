from django.test import Client, TestCase
from django.urls import reverse

from appsettings.models import AppSettings
from appsettings.settings import app_settings, get_settings


class AppSettingsTestCase(TestCase):
    def setUp(self):
        self.client.login(username="admin", password="admin")

    def test_get_settings_populates_singleton(self):
        AppSettings.objects.update_or_create(
            key="CUSTOM_TEST_SETTING",
            defaults={"value": "test_value_123", "name": "Custom Test Setting"}
        )
        get_settings()
        self.assertEqual(getattr(app_settings, "CUSTOM_TEST_SETTING", None), "test_value_123")

    def test_appsettings_view_get(self):
        response = self.client.get(reverse("appsettings"))
        self.assertEqual(response.status_code, 200)

    def test_appsettings_update_setting(self):
        setting = AppSettings.objects.get(key="SHOW_ACCESS_ROOT_PASSWORD")
        original_value = setting.value
        new_val = "False" if original_value == "True" else "True"

        response = self.client.post(
            reverse("appsettings"),
            {
                "SHOW_ACCESS_ROOT_PASSWORD": new_val
            }
        )
        self.assertRedirects(response, reverse("appsettings"))

        setting.refresh_from_db()
        self.assertEqual(setting.value, new_val)
