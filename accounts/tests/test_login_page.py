"""The sign-in page: a failed sign-in keeps the username and puts the cursor
on the password, a locked user gets a page with the lock time, and the
administrator's notice from the Settings page is shown above the form; a sign-in
lasts the hours set there, and a superuser can end a lock."""

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


@override_settings(OTP_ENABLED=False)
class SessionLengthTests(TestCase):
    def test_a_sign_in_lasts_the_hours_from_the_settings_page(self):
        get_user_model().objects.create_user("sl-user", password="right-pass-1")
        self.client.post(reverse("accounts:login"), {"username": "sl-user", "password": "right-pass-1"})
        self.assertAlmostEqual(self.client.session.get_expiry_age(), 24 * 3600, delta=5)
        AppSettings.objects.filter(key="LOGIN_SESSION_HOURS").update(value="2")
        self.client.post(reverse("accounts:logout"))
        self.client.post(reverse("accounts:login"), {"username": "sl-user", "password": "right-pass-1"})
        self.assertAlmostEqual(self.client.session.get_expiry_age(), 2 * 3600, delta=5)
        # a later save of the session does not move the end
        end = self.client.session.get_expiry_date()
        session = self.client.session
        session["touched"] = True
        session.save()
        self.assertEqual(self.client.session.get_expiry_date(), end)


@override_settings(OTP_ENABLED=False)
class UnlockTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("ul-user", password="right-pass-1")
        self.admin = User.objects.create_superuser("ul-admin", "ul@example.com", "admin-pass-1")
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="2")
        # one failure from each of two browsers at the same address, one typed in capitals
        self.client.post(reverse("accounts:login"), {"username": "ul-user", "password": "wrong"},
                         HTTP_USER_AGENT="browser-a")
        self.client.post(reverse("accounts:login"), {"username": "UL-User", "password": "wrong"},
                         HTTP_USER_AGENT="browser-b")
        self.client.post(reverse("accounts:login"), {"username": "ul-user", "password": "wrong"},
                         HTTP_USER_AGENT="browser-b")

    def sign_in_works(self):
        client = self.client_class()
        return client.post(reverse("accounts:login"), {"username": "ul-user", "password": "right-pass-1"}).status_code == 302

    def test_the_lock_is_shown_and_a_superuser_ends_it(self):
        self.assertFalse(self.sign_in_works())
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("admin:user_list")), "Sign-in locked")
        self.assertContains(self.client.get(reverse("accounts:account", args=[self.user.pk])), "Unlock sign-in")
        self.client.post(reverse("accounts:admin_unlock", args=[self.user.pk]))
        self.assertTrue(self.sign_in_works())
        self.assertNotContains(self.client.get(reverse("accounts:account", args=[self.user.pk])), "Sign-in locked")
        from logs.models import Logs
        self.assertTrue(Logs.objects.filter(message__icontains="unlock sign-in").exists())

    def test_only_a_superuser_unlocks(self):
        other = get_user_model().objects.create_user("ul-other", password="other-pass-1")
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("accounts:admin_unlock", args=[self.user.pk])).status_code, 403)
        self.assertFalse(self.sign_in_works())


@override_settings(OTP_ENABLED=False)
class BlockEndsSessionsTests(TestCase):
    def test_a_blocked_user_is_signed_out(self):
        User = get_user_model()
        User.objects.create_user("bl-user", password="right-pass-1")
        user_client = self.client_class()
        user_client.post(reverse("accounts:login"), {"username": "bl-user", "password": "right-pass-1"})
        self.client.force_login(User.objects.create_superuser("bl-admin", "bl@example.com", "admin-pass-1"))
        self.client.post(reverse("admin:user_block", args=[User.objects.get(username="bl-user").pk]))
        self.assertEqual(user_client.get(reverse("instances:index")).status_code, 302)
        from django.contrib.sessions.models import Session
        self.assertEqual(Session.objects.count(), 1)  # the administrator's
