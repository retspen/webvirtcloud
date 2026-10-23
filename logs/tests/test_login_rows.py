"""Logins, failed logins, lockouts and logouts write rows on the Logs page."""

from appsettings.models import AppSettings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from logs.models import Logs


def rows():
    return list(Logs.objects.order_by("id").values_list("user", "host", "message", "success", "ip"))


@override_settings(OTP_ENABLED=False)
class LoginRowsTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("bob", password="right-pass-1")
        AppSettings.objects.filter(key="LOGIN_FAILURE_LIMIT").update(value="3")

    def login(self, password, username="bob"):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password})

    def test_a_login_and_a_logout_write_rows(self):
        self.assertEqual(self.login("right-pass-1").status_code, 302)
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(rows(), [
            ("bob", "-", "Login", True, "127.0.0.1"),
            ("bob", "-", "Logout", True, "127.0.0.1"),
        ])

    def test_a_failed_login_writes_the_typed_username(self):
        self.assertEqual(self.login("wrong").status_code, 200)
        self.assertEqual(rows(), [("bob", "-", "Login failed", False, "127.0.0.1")])

    def test_an_empty_username_is_no_attempt(self):
        # the form stops it before authentication: no row and no error
        self.assertEqual(self.login("wrong", username="").status_code, 200)
        self.assertEqual(rows(), [])

    def test_the_attempt_at_the_limit_and_one_while_locked(self):
        self.login("wrong")
        self.login("wrong")
        self.assertEqual(self.login("wrong").status_code, 429)
        # django-axes sends the lockout from its own failure receiver, before ours
        messages = [r[2] for r in rows()]
        self.assertEqual(messages, ["Login failed", "Login failed", "Locked out", "Login failed"])

        self.assertEqual(self.login("right-pass-1").status_code, 429)
        self.assertEqual([r[2] for r in rows()][4:], ["Locked out", "Login failed"])
        self.assertTrue(all(r[0] == "bob" and r[3] is False for r in rows()))


@override_settings(OTP_ENABLED=False)
class LoginRowInputTests(TestCase):
    """S-16: what a failed login writes cannot break the row or forge another record."""

    def login(self, username):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": "wrong"})

    def test_an_oversized_username_is_cut_to_the_field(self):
        self.assertEqual(self.login("x" * 300).status_code, 200)
        self.assertEqual(rows(), [("x" * 150, "-", "Login failed", False, "127.0.0.1")])

    def test_a_crlf_username_stays_in_its_row(self):
        forged = "bob\r\nadmin - Login"
        self.login(forged)
        self.assertEqual(rows(), [(forged, "-", "Login failed", False, "127.0.0.1")])
        admin = get_user_model().objects.create_superuser("s16-admin", "s16@example.com", "pw")
        self.client.force_login(admin)
        page = self.client.get(reverse("admin:logs")).content.decode()
        self.assertEqual(page.count("Login failed"), 1)

    def test_a_crlf_username_is_one_line_in_the_file_log(self):
        from unittest.mock import patch

        with patch.object(Logs.objects, "create", side_effect=RuntimeError("db down")), \
                self.assertLogs("logs.audit", "WARNING") as logged:
            self.login("bob\r\nforged record")
        [line] = logged.output
        self.assertNotIn("\r", line)
        self.assertNotIn("\n", line)
