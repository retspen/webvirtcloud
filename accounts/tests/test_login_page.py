"""The sign-in page: a failed sign-in keeps the username and puts the cursor
on the password, a locked user gets a page with the lock time, and the
administrator's notice from the Settings page is shown above the form."""

from appsettings.models import AppSettings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(OTP_ENABLED=False)
class LoginPageTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("lp-user", password="right-pass-1")

    def login(self, password, username="lp-user", url=None):
        return self.client.post(url or reverse("accounts:login"), {"username": username, "password": password})

    def test_a_failed_sign_in_keeps_the_username_and_marks_the_password(self):
        page = self.login("wrong").content.decode()
        self.assertIn('value="lp-user"', page)
        self.assertRegex(page, r'id="id_password" class="form-control is-invalid"[^>]*autofocus')
        self.assertNotRegex(page, r'id="id_username"[^>]*autofocus')

    def test_a_username_error_keeps_the_cursor_on_the_username(self):
        page = self.login("right-pass-1", username="u" * 151).content.decode()
        self.assertRegex(page, r'id="id_username"[^>]*autofocus')
        self.assertNotIn("is-invalid", page)

    def test_the_lock_page_links_back_with_the_destination(self):
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="1")
        url = reverse("accounts:login") + "?next=/computes/"
        self.login("wrong", url=url)
        self.assertContains(self.login("wrong", url=url), 'href="%s?next=/computes/"' % reverse("accounts:login"),
                            status_code=429)

    def test_the_empty_page_focuses_the_username(self):
        page = self.client.get(reverse("accounts:login")).content.decode()
        self.assertRegex(page, r'id="id_username"[^>]*autocomplete="username"[^>]*autofocus')
        self.assertIn('autocomplete="current-password"', page)
        self.assertIn('id="caps-lock"', page)

    def test_a_locked_user_gets_the_lock_page_with_the_lock_time(self):
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="2")
        AppSettings.objects.filter(key="LOGIN_LOCKOUT_MINUTES").update(value="20")
        self.login("wrong")
        self.login("wrong")
        response = self.login("right-pass-1")
        self.assertEqual(response.status_code, 429)
        self.assertTemplateUsed(response, "accounts/lockout.html")
        self.assertContains(response, "The lock ends within 20 minutes.", status_code=429)

    def test_the_notice_is_shown_only_when_set(self):
        self.assertNotContains(self.client.get(reverse("accounts:login")), "alert-info")
        AppSettings.objects.filter(key="LOGIN_NOTICE").update(value="Maintenance at <22:00>")
        self.assertContains(self.client.get(reverse("accounts:login")), "Maintenance at &lt;22:00&gt;")
