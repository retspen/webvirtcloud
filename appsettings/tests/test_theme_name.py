"""The settings page picks one of the prebuilt themes in static/css/themes;
every page links the chosen theme's file."""

from appsettings.models import AppSettings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from lxml import html


class ThemeNameTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("th-admin", "th@example.com", "pw"))
        self.before = AppSettings.objects.get(key="BOOTSTRAP_THEME").value

    def theme_link(self, url):
        (href,) = html.fromstring(self.client.get(url).content).xpath("//link[@id='wvc_css']/@href")
        return href

    def test_a_name_that_is_not_a_theme_is_refused(self):
        for theme in ("../../etc", "flatly.min.css", "nope", ""):
            with self.subTest(theme=theme):
                self.client.post(reverse("appsettings"), {"BOOTSTRAP_THEME": theme})
                self.assertEqual(AppSettings.objects.get(key="BOOTSTRAP_THEME").value, self.before)

    def test_pages_link_the_chosen_theme(self):
        self.assertEqual(self.theme_link(reverse("appsettings")), "/static/css/themes/zephyr.min.css")
        self.client.post(reverse("appsettings"), {"BOOTSTRAP_THEME": "flatly"})
        self.assertEqual(AppSettings.objects.get(key="BOOTSTRAP_THEME").value, "flatly")
        self.assertEqual(self.theme_link(reverse("appsettings")), "/static/css/themes/flatly.min.css")
