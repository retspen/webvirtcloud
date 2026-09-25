import base64
import struct
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.utils import get_user_totp_device, send_email_with_otp, validate_ssh_key


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

    def test_validate_ssh_key_invalid_parts(self):
        self.assertFalse(validate_ssh_key("only_two parts"))
        self.assertFalse(validate_ssh_key("one_part"))
        self.assertFalse(validate_ssh_key("four parts key here now"))

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

    def test_send_email_with_otp(self):
        device = get_user_totp_device(self.user)
        send_email_with_otp(self.user, device)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("OTP QR Code", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["user@example.com"])
