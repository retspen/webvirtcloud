import base64
import hashlib
import re
import struct
import zlib
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django_otp.plugins.otp_totp.models import TOTPDevice
from lxml import html

from accounts.utils import (get_existing_totp_device, get_user_totp_device, send_email_with_otp, validate_ssh_key)


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

    def test_send_email_with_otp(self):
        device = get_user_totp_device(self.user)
        send_email_with_otp(self.user, device)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("OTP QR Code", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["user@example.com"])
        # the QR code as inline SVG and, for clients without SVG, as a PNG data URI
        doc = html.fromstring(mail.outbox[0].alternatives[0][0])
        self.assertEqual(len(doc.xpath("//svg")), 1)
        (img,) = doc.xpath("//img")
        self.assertEqual(img.get("alt"), device.config_url)
        self.assertTrue(base64.b64decode(img.get("src").removeprefix("data:image/png;base64,")).startswith(b"\x89PNG"))

    def test_otp_email_qr_codes_are_what_django_qr_code_drew(self):
        # sha256 of the SVG and the PNG django-qr-code 4.2.0 made for this URL
        url = "otpauth://totp/WebVirtCloud:alice?secret=JBSWY3DPEHPK3PXP&issuer=WebVirtCloud"
        with patch("accounts.utils.send_mail") as send:
            send_email_with_otp(self.user, SimpleNamespace(config_url=url))
        page = send.call_args.kwargs["html_message"]
        svg = re.search(r"<svg.*?</svg>", page, re.S).group(0)
        png = base64.b64decode(re.search(r'<img src="data:image/png;base64,([^"]+)"', page).group(1))
        self.assertEqual(hashlib.sha256(svg.encode()).hexdigest(), "b57323be725891af13d862a3a3351cac3ac64a493793c0258cf3e4a5886467c2")
        # the PNG's header and pixel rows: its compressed bytes depend on the zlib build
        chunks, pos = {}, 8
        while pos < len(png):
            size, kind = struct.unpack(">I4s", png[pos:pos + 8])
            chunks[kind] = chunks.get(kind, b"") + png[pos + 8:pos + 8 + size]
            pos += 12 + size
        self.assertEqual(hashlib.sha256(chunks[b"IHDR"] + zlib.decompress(chunks[b"IDAT"])).hexdigest(), "cca16de611c73468827f70001f69dc2e48633e6aae2b570a9391eb40a1f8ae88")
