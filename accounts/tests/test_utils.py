import base64
import hashlib
import re
import struct
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice
from lxml import html

from accounts.utils import (OTP_LINK, OTP_LINK_MAX_AGE, get_existing_totp_device, get_user_totp_device, otp_qr_svg,
                            send_email_with_otp, validate_ssh_key)


class AccountsUtilsTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="test_otp_user", email="user@example.com", password="password123"
        )

    def test_validate_ssh_key_valid(self):
        blob = (
            struct.pack(">I", 7)
            + b"ssh-rsa"
            + struct.pack(">I", 3)
            + b"\x01\x00\x01"
            + struct.pack(">I", 8)
            + b"\x00" * 8
        )
        b64 = base64.b64encode(blob).decode()
        valid_key = f"ssh-rsa {b64} user@example.com"
        self.assertTrue(validate_ssh_key(valid_key))
        # ssh-keygen -C "John Doe laptop": the comment holds spaces
        self.assertTrue(validate_ssh_key(f"ssh-rsa {b64} John Doe laptop"))
        self.assertTrue(validate_ssh_key(f"ssh-rsa {b64}"))

    def test_validate_ssh_key_invalid_parts(self):
        self.assertFalse(validate_ssh_key("only_two parts"))
        self.assertFalse(validate_ssh_key("one_part"))

    def test_validate_ssh_key_invalid_base64(self):
        self.assertFalse(validate_ssh_key("ssh-rsa not-valid-b64! user@example.com"))

    def test_validate_ssh_key_struct_error(self):
        # Base64 with less than 4 bytes cannot unpack length
        short_b64 = base64.b64encode(b"ab").decode()
        self.assertFalse(validate_ssh_key(f"ssh-rsa {short_b64} user@example.com"))

    def test_validate_ssh_key_type_mismatch(self):
        blob = struct.pack(">I", 7) + b"ssh-rsa" + b"\x00" * 8
        b64 = base64.b64encode(blob).decode()
        # header says ssh-ed25519 but payload has ssh-rsa
        self.assertFalse(validate_ssh_key(f"ssh-ed25519 {b64} user@example.com"))

    def test_get_user_totp_device_creates_new(self):
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 0)
        device = get_user_totp_device(self.user)
        self.assertIsInstance(device, TOTPDevice)
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 1)

    def test_get_user_totp_device_retrieves_existing(self):
        device1 = get_user_totp_device(self.user)
        device2 = get_user_totp_device(self.user)
        self.assertEqual(device1.id, device2.id)
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 1)

    def test_get_existing_totp_device_returns_none_without_a_device(self):
        self.assertIsNone(get_existing_totp_device(self.user))
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 0)

    def test_get_existing_totp_device_ignores_unconfirmed(self):
        TOTPDevice.objects.create(user=self.user, confirmed=False)
        self.assertIsNone(get_existing_totp_device(self.user))

    def test_get_existing_totp_device_returns_confirmed(self):
        device = TOTPDevice.objects.create(user=self.user, confirmed=True)
        self.assertEqual(get_existing_totp_device(self.user).id, device.id)

    def test_the_device_is_made_under_a_lock_on_the_user(self):
        from django.db.models.query import QuerySet

        with patch.object(QuerySet, "select_for_update", autospec=True, side_effect=QuerySet.select_for_update) as lock:
            device = get_user_totp_device(self.user)
        lock.assert_called_once()
        self.assertEqual(get_user_totp_device(self.user), device)

    @override_settings(OTP_ENABLED=True)
    def test_the_mail_links_to_the_qr_code_and_holds_no_secret(self):
        device = get_user_totp_device(self.user)
        send_email_with_otp(RequestFactory().get("/"), device)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual((message.subject, message.to, message.alternatives), ("OTP QR Code", ["user@example.com"], []))
        self.assertNotIn(device.bin_key.hex(), message.body)
        self.assertNotIn("otpauth", message.body)
        # the token is the fragment, which no request (no access log) carries
        path, token = re.search(r"http://testserver(/\S+)#(\S+)", message.body).groups()
        self.assertEqual(path, reverse("accounts:otp_qr"))
        page = html.fromstring(self.client.get(path).content)
        self.assertEqual((page.xpath("//svg"), page.xpath("//form[@id='otp-qr-form']/input[@name='token']/@type")), ([], ["hidden"]))
        self.assertEqual(page.xpath("//script/@src")[-1], "/static/js/otp_qr.js")
        shown = self.client.post(path, {"token": token})
        self.assertEqual(shown["Cache-Control"], "no-store")
        self.assertEqual(len(html.fromstring(shown.content).xpath("//svg")), 1)

    @override_settings(OTP_ENABLED=True)
    def test_a_link_that_is_old_or_not_signed_shows_nothing(self):
        token = OTP_LINK.sign(str(get_user_totp_device(self.user).pk))
        with patch("django.core.signing.time.time", return_value=time.time() + OTP_LINK_MAX_AGE + 1):
            self.assertEqual(self.client.post(reverse("accounts:otp_qr"), {"token": token}).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:otp_qr"), {"token": f"{self.user.pk}:x:y"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:otp_qr")).status_code, 404)

    def test_the_qr_code_is_what_django_qr_code_drew(self):
        # sha256 of the SVG django-qr-code 4.2.0 made for this URL
        url = "otpauth://totp/WebVirtCloud:alice?secret=JBSWY3DPEHPK3PXP&issuer=WebVirtCloud"
        svg = str(otp_qr_svg(SimpleNamespace(config_url=url)))
        self.assertEqual(hashlib.sha256(svg.encode()).hexdigest(), "b57323be725891af13d862a3a3351cac3ac64a493793c0258cf3e4a5886467c2")
