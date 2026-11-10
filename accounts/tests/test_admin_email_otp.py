from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.signing import TimestampSigner
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.utils import OTP_LINK
from logs.models import Logs


class AdminEmailOtpTestCase(TestCase):
    """Sending the OTP QR code by email must not happen on GET."""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="otp_super", email="otp_super@example.com", password="x"
        )
        self.user = User.objects.create_user(
            username="otp_user", email="otp_user@example.com", password="x"
        )
        self.client.force_login(self.superuser)
        self.url = reverse("accounts:admin_email_otp", args=[self.user.id])

    @patch("accounts.views.send_email_with_otp")
    def test_get_does_not_send_email(self, mock_send):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        mock_send.assert_not_called()

    @patch("accounts.views.send_email_with_otp")
    def test_post_sends_email(self, mock_send):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()

    @patch("accounts.views.send_email_with_otp", side_effect=ConnectionRefusedError)
    def test_a_mail_that_did_not_go_leaves_the_user_without_otp(self, mock_send):
        self.client.post(self.url)
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())

    @override_settings(OTP_ENABLED=True)
    def test_a_reset_forgets_the_device_and_the_links_mailed_for_it(self):
        with patch("accounts.views.send_email_with_otp") as send:
            self.client.post(self.url)
        old_link = OTP_LINK.sign(str(send.call_args.args[1].pk))
        self.assertContains(self.client.get(reverse("accounts:account", args=[self.user.id])), "Reset OTP")
        response = self.client.post(reverse("accounts:admin_reset_otp", args=[self.user.id]), follow=True)
        self.assertContains(response, "OTP of otp_user was reset")
        self.assertNotContains(response, "Reset OTP")
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertEqual(Logs.objects.get(message="User otp_user: reset OTP").success, True)
        # the old mail does not show the new device's secret
        with patch("accounts.views.send_email_with_otp"):
            self.client.post(self.url)
        self.assertEqual(self.client.post(reverse("accounts:otp_qr"), {"token": old_link}).status_code, 404)

    @override_settings(OTP_ENABLED=True)
    def test_a_link_that_named_a_user_does_not_open_a_device_with_that_id(self):
        device = TOTPDevice.objects.create(user=self.superuser, confirmed=True)
        user_link = TimestampSigner(salt="accounts.otp_qr").sign(str(device.pk))
        self.assertEqual(self.client.post(reverse("accounts:otp_qr"), {"token": user_link}).status_code, 404)

    def test_the_smtp_connection_waits_a_bounded_time(self):
        from django.core.mail.backends.smtp import EmailBackend

        # None would wait for a server that stopped answering forever
        self.assertIsNotNone(EmailBackend().timeout)
