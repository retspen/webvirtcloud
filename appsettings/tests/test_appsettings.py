from django.contrib.messages import get_messages
from django.test import RequestFactory, TestCase
from django.urls import reverse

from appsettings.models import AppSettings
from appsettings.settings import app_settings, get_settings


class AppSettingsTestCase(TestCase):
    def setUp(self):
        self.client.login(request=RequestFactory().get("/"), username="admin", password="admin")

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

    def test_appsettings_non_superuser_forbidden(self):
        from django.contrib.auth.models import User
        regular_user = User.objects.create_user(username="regular", password="pwd")
        self.client.force_login(regular_user)
        response = self.client.get(reverse("appsettings"))
        self.assertEqual(response.status_code, 403)

    def test_clones_are_not_migrated_automatically(self):
        # a clone stays on the host of the VM it was made from; the setting
        # that sent it to a random host is removed by migration 0015
        self.assertFalse(AppSettings.objects.filter(key="CLONE_INSTANCE_AUTO_MIGRATE").exists())

    def test_worker_settings_refuse_values_out_of_bounds(self):
        response = self.client.post(reverse("appsettings"), {"WORKER_CONCURRENCY": "0"})
        self.assertEqual(AppSettings.objects.get(key="WORKER_CONCURRENCY").value, "4")
        self.assertTrue(any("between 1 and 16" in str(m) for m in get_messages(response.wsgi_request)))

    def post(self, key, value):
        response = self.client.post(reverse("appsettings"), {key: value})
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_a_listed_setting_takes_only_its_choices(self):
        messages = self.post("INSTANCE_FIRMWARE_DEFAULT_TYPE", "Coreboot")
        self.assertEqual(AppSettings.objects.get(key="INSTANCE_FIRMWARE_DEFAULT_TYPE").value, "BIOS")
        self.assertTrue(any("BIOS, UEFI" in m for m in messages), messages)

    def test_number_settings_take_whole_numbers_in_their_range(self):
        # read with int() elsewhere: a letter would break the logs page or VM create
        for key, bad, good in (("LOGS_PER_PAGE", "abc", "50"), ("LOGS_PER_PAGE", "0", "1000"),
                               ("INSTANCE_VOLUME_DEFAULT_OWNER_UID", "-1", "107"),
                               ("INSTANCE_VOLUME_DEFAULT_OWNER_GID", "x", "4294967294"),
                               ("LOGIN_FAILURE_LIMIT", "0", "10"), ("SNAPSHOT_FREE_SPACE_PERCENT", "101", "0")):
            with self.subTest(key=key, bad=bad):
                before = AppSettings.objects.get(key=key).value
                self.assertTrue(any("whole number" in m for m in self.post(key, bad)))
                self.assertEqual(AppSettings.objects.get(key=key).value, before)
                self.post(key, good)
                self.assertEqual(AppSettings.objects.get(key=key).value, good)

    def test_the_clone_name_prefix_is_text(self):
        self.post("CLONE_INSTANCE_DEFAULT_PREFIX", "web-")
        self.assertEqual(AppSettings.objects.get(key="CLONE_INSTANCE_DEFAULT_PREFIX").value, "web-")
        page = self.client.get(reverse("appsettings")).content.decode()
        self.assertIn('name="CLONE_INSTANCE_DEFAULT_PREFIX" value="web-"', page)

