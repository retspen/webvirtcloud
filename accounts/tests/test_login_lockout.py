"""Failed logins lock a username for the address it is tried from
(django-axes). The number of attempts and the lock time come from the
Settings page."""

from datetime import timedelta

from appsettings.models import AppSettings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.lockout import client_ip, cooloff_time, failure_limit


@override_settings(OTP_ENABLED=False)
class LoginLockoutTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("lo-user", password="right-pass-1")
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="3")

    def login(self, password, ip="203.0.113.10", via_proxy=True):
        meta = {"REMOTE_ADDR": "127.0.0.1", "HTTP_X_REAL_IP": ip} if via_proxy else {"REMOTE_ADDR": ip}
        return self.client.post(reverse("accounts:login"), {"username": "lo-user", "password": password}, **meta)

    def test_the_limit_from_the_settings_page_locks_the_user_at_that_address(self):
        for _ in range(3):
            self.login("wrong")
        self.assertEqual(self.login("right-pass-1").status_code, 429)
        # another address is not locked: an attacker cannot lock someone out
        self.assertEqual(self.login("right-pass-1", ip="198.51.100.7").status_code, 302)

    def test_a_successful_login_starts_the_count_again(self):
        self.login("wrong")
        self.login("wrong")
        self.assertEqual(self.login("right-pass-1").status_code, 302)
        self.client.logout()
        self.login("wrong")
        self.login("wrong")
        self.assertEqual(self.login("right-pass-1").status_code, 302)

    def test_a_successful_login_is_logged_on_the_logs_page_only(self):
        from axes.models import AccessLog
        from logs.models import Logs

        self.assertEqual(self.login("right-pass-1").status_code, 302)
        self.assertTrue(Logs.objects.filter(user="lo-user").exists())
        self.assertFalse(AccessLog.objects.exists())

    def test_the_proxy_header_is_trusted_only_from_the_local_proxy(self):
        # direct requests: X-Real-IP is ignored, so changing it does not escape the lock
        for n in range(3):
            self.client.post(reverse("accounts:login"), {"username": "lo-user", "password": "wrong"},
                             REMOTE_ADDR="203.0.113.20", HTTP_X_REAL_IP=f"10.0.0.{n}")
        response = self.client.post(reverse("accounts:login"), {"username": "lo-user", "password": "right-pass-1"},
                                    REMOTE_ADDR="203.0.113.20", HTTP_X_REAL_IP="10.0.0.99")
        self.assertEqual(response.status_code, 429)


class LockoutSettingsTests(TestCase):
    def request(self, remote, real_ip=None):
        meta = {"REMOTE_ADDR": remote}
        if real_ip:
            meta["HTTP_X_REAL_IP"] = real_ip
        return RequestFactory().post("/", **meta)

    def test_values_from_the_settings_page(self):
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="7")
        AppSettings.objects.filter(key="LOGIN_LOCKOUT_MINUTES").update(value="30")
        self.assertEqual(failure_limit(None, {}), 7)
        self.assertEqual(cooloff_time(None), timedelta(minutes=30))

    def test_defaults_and_invalid_values(self):
        for value in ("", "abc", "0", "-3"):
            with self.subTest(value=value):
                AppSettings.objects.filter(key__in=["LOGIN_FAILURE_LIMIT", "LOGIN_LOCKOUT_MINUTES"]).update(value=value)
                self.assertEqual(failure_limit(None, {}), 5)
                self.assertEqual(cooloff_time(None), timedelta(minutes=15))

    def test_client_ip(self):
        self.assertEqual(client_ip(self.request("127.0.0.1", "203.0.113.5")), "203.0.113.5")
        self.assertEqual(client_ip(self.request("::1", "203.0.113.5")), "203.0.113.5")
        self.assertEqual(client_ip(self.request("127.0.0.1")), "127.0.0.1")
        self.assertEqual(client_ip(self.request("198.51.100.2", "203.0.113.5")), "198.51.100.2")

    def test_client_ip_behind_a_configured_proxy(self):
        with self.settings(LOGIN_TRUSTED_PROXIES=["172.18.0.0/16", "10.0.0.5"]):
            self.assertEqual(client_ip(self.request("172.18.3.4", "203.0.113.5")), "203.0.113.5")
            self.assertEqual(client_ip(self.request("10.0.0.5", "203.0.113.6")), "203.0.113.6")
            self.assertEqual(client_ip(self.request("10.0.0.6", "203.0.113.6")), "10.0.0.6")


class SettingsPageTests(TestCase):
    def test_both_values_are_on_the_settings_page(self):
        self.client.force_login(get_user_model().objects.create_superuser("lo-admin", "lo@example.com", "pw"))
        page = self.client.get(reverse("appsettings")).content.decode()
        self.assertIn('name="LOGIN_FAILURE_LIMIT"', page)
        self.assertIn('name="LOGIN_LOCKOUT_MINUTES"', page)
        self.client.post(reverse("appsettings"), {"LOGIN_LOCKOUT_MINUTES": "45"})
        self.assertEqual(cooloff_time(None), timedelta(minutes=45))
