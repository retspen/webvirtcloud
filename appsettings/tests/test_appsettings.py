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

    def page(self):
        from lxml import html

        return html.fromstring(self.client.get(reverse("appsettings")).content)

    def test_settings_are_grouped_with_their_descriptions_shown(self):
        page = self.page()
        titles = [h.text_content().strip() for h in page.xpath("//form//h2")]
        self.assertEqual(titles[:3], ["New VM defaults", "Disks", "Clones"])
        # every setting is in one group, with a label tied to its field and its description shown
        keys = page.xpath("//form//*[self::input or self::select][@name and @name!='csrfmiddlewaretoken' and not(starts-with(@name, 'was-'))]/@name")
        names = set(AppSettings.objects.exclude(key="BOOTSTRAP_THEME").values_list("key", flat=True))
        self.assertEqual(sorted(k for k in keys if k not in ("BOOTSTRAP_THEME", "language")), sorted(names))
        (field,) = page.xpath("//*[@name='LOGS_PER_PAGE']")
        self.assertEqual((field.get("type"), field.get("min"), field.get("max")), ("number", "1", "1000"))
        self.assertEqual(page.xpath(f"//label[@for='{field.get('id')}']/text()"), ["Logs per Page"])
        self.assertEqual(page.xpath(f"//*[@id='{field.get('aria-describedby')}']/text()"), ["Rows per page on the Logs page"])
        # a group is saved with its button, not on every change
        self.assertEqual(page.xpath("//*[@onchange]"), [])

    def test_a_group_saves_its_changed_settings_only(self):
        from logs.models import Logs

        Logs.objects.all().delete()
        response = self.client.post(reverse("appsettings"), {
            "CONSOLE_SCALE": "True", "CONSOLE_VIEW_ONLY": "False",
            "CONSOLE_RESIZE_SESSION": "False", "CONSOLE_CLIP_VIEWPORT": "True"})
        self.assertRedirects(response, reverse("appsettings"))
        values = dict(AppSettings.objects.filter(key__startswith="CONSOLE_").values_list("key", "value"))
        self.assertEqual(values, {"CONSOLE_SCALE": "True", "CONSOLE_VIEW_ONLY": "False",
                                  "CONSOLE_RESIZE_SESSION": "False", "CONSOLE_CLIP_VIEWPORT": "True"})
        # one row for the group's save
        self.assertEqual(list(Logs.objects.values_list("message", flat=True)),
                         ["Settings: change Console Clip Viewport to True, Console Scale to True"])
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ["Saved: Console Clip Viewport, Console Scale"])

    def test_a_group_keeps_what_another_administrator_saved_meanwhile(self):
        # both opened the page with 5 and 15; the first saved 10 for the limit
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="10")
        self.client.post(reverse("appsettings"), {"LOGIN_FAILURE_LIMIT": "5", "was-LOGIN_FAILURE_LIMIT": "5",
                                                  "LOGIN_LOCKOUT_MINUTES": "30", "was-LOGIN_LOCKOUT_MINUTES": "15"})
        values = dict(AppSettings.objects.filter(key__startswith="LOGIN_").values_list("key", "value"))
        self.assertEqual(values, {"LOGIN_FAILURE_LIMIT": "10", "LOGIN_LOCKOUT_MINUTES": "30"})

    def test_a_failed_save_changes_none_of_its_group(self):
        from unittest.mock import patch

        from django.db import DatabaseError

        saves = []

        def save(setting, *args, **kwargs):
            saves.append(setting.key)
            if len(saves) == 2:
                raise DatabaseError("disk full")
            return original(setting, *args, **kwargs)

        original = AppSettings.save
        with patch.object(AppSettings, "save", save):
            self.client.post(reverse("appsettings"), {"CONSOLE_SCALE": "True", "CONSOLE_CLIP_VIEWPORT": "True"})
        values = dict(AppSettings.objects.filter(key__in=["CONSOLE_SCALE", "CONSOLE_CLIP_VIEWPORT"]).values_list("key", "value"))
        self.assertEqual(values, {"CONSOLE_SCALE": "False", "CONSOLE_CLIP_VIEWPORT": "False"})

    def test_one_bad_value_saves_nothing_of_its_group(self):
        response = self.client.post(reverse("appsettings"), {"LOGIN_FAILURE_LIMIT": "10", "LOGIN_LOCKOUT_MINUTES": "x"})
        self.assertEqual(AppSettings.objects.get(key="LOGIN_FAILURE_LIMIT").value, "5")
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ["Login Lockout Minutes must be a whole number between 1 and 10080"])

