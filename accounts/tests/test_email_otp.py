"""The "Lost OTP?" page mails a user their OTP QR code without a login. It
exists only while OTP is enabled; it resends the QR only to a user who
has already enrolled (it never creates a device), mails one exact match at
most once per interval, and never fails with an error page."""

from django.contrib.auth import get_user_model
from django_otp.plugins.otp_totp.models import TOTPDevice
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from logs.models import Logs

URL = reverse("accounts:email_otp")


@override_settings(
    OTP_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "email-otp-tests"}},
)
class EmailOTPTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("otp-user", email="otp.user@example.com", password="x")

    def enroll(self, user=None):
        return TOTPDevice.objects.create(user=user or self.user, confirmed=True)

    def post(self, email):
        response = self.client.post(URL, {"email": email})
        self.assertRedirects(response, reverse("accounts:login"), fetch_redirect_response=False)
        return response

    def test_one_mail_to_an_enrolled_user(self):
        self.enroll()
        self.post("OTP.User@Example.com")  # addresses match case-insensitively
        self.assertEqual([m.to for m in mail.outbox], [["otp.user@example.com"]])
        # the requester is anonymous: the row does not make it the user
        self.assertEqual(list(Logs.objects.values_list("user", "message", "success", "ip")),
                         [("", "User otp-user: mail OTP QR code (lost OTP)", True, "127.0.0.1")])

    def test_an_unenrolled_user_gets_no_mail_and_no_device(self):
        self.post("otp.user@example.com")
        self.assertEqual(mail.outbox, [])
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())

    def test_repeated_requests_send_one_mail_per_interval(self):
        self.enroll()
        for _ in range(20):
            self.post("otp.user@example.com")
        self.assertEqual(len(mail.outbox), 1)

    def test_an_address_of_two_users_sends_nothing(self):
        get_user_model().objects.create_user("otp-twin", email="otp.user@example.com", password="x")
        self.post("otp.user@example.com")
        self.assertEqual(mail.outbox, [])

    def test_unknown_and_inactive_addresses_send_nothing(self):
        get_user_model().objects.create_user("otp-gone", email="gone@example.com", password="x", is_active=False)
        self.post("nobody@example.com")
        self.post("gone@example.com")
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1", EMAIL_PORT=1)
    def test_a_mail_server_that_is_down_is_no_error_page(self):
        self.enroll()
        with self.assertLogs("accounts.views", level="ERROR"):
            self.post("otp.user@example.com")
        self.assertIs(Logs.objects.get(message__startswith="User otp-user: mail OTP QR code (lost OTP):").success, False)


@override_settings(OTP_ENABLED=False)
class EmailOTPDisabledTests(TestCase):
    def test_the_page_does_not_exist_without_otp(self):
        get_user_model().objects.create_user("otp-off", email="off@example.com", password="x")
        self.assertEqual(self.client.get(URL).status_code, 404)
        self.assertEqual(self.client.post(URL, {"email": "off@example.com"}).status_code, 404)
        self.assertEqual(mail.outbox, [])
