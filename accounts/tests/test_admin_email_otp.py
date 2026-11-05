from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


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

    def test_the_smtp_connection_waits_a_bounded_time(self):
        from django.core.mail.backends.smtp import EmailBackend

        # None would wait for a server that stopped answering forever
        self.assertIsNotNone(EmailBackend().timeout)
