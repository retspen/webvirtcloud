"""Changes to a user's own account, VM ownership, OTP mails and SSH keys write rows on the Logs page."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserAttributes
from logs.models import Logs


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class OwnAccountRowTests(TestCase):
    def setUp(self):
        self.bob = get_user_model().objects.create_user("bob", password="Bob-pass-2026")
        self.client.force_login(self.bob)
        Logs.objects.all().delete()  # the login's row

    def test_own_profile_and_password(self):
        self.client.post(reverse("accounts:profile"), {"username": "bob", "email": "bob@example.com"})
        self.client.post(reverse("accounts:change_password"), {
            "old_password": "Bob-pass-2026", "new_password1": "Bob-new-pass-1", "new_password2": "Bob-new-pass-1"})
        self.assertEqual(rows(), [("User bob: change email", True), ("User bob: change password", True)])
        self.assertFalse(Logs.objects.filter(message__contains="pass-").exists())

    def test_the_first_login_password_change(self):
        self.bob.user_permissions.clear()
        UserAttributes.objects.update_or_create(user=self.bob, defaults={"must_change_password": True})
        self.client.post(reverse("accounts:change_password"), {
            "old_password": "Bob-pass-2026", "new_password1": "Bob-new-pass-1", "new_password2": "Bob-new-pass-1"})
        self.assertEqual(rows(), [("User bob: change password", True)])


SSH_KEY = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC6OOdbfv27QVnSC6sKxGaHb6YFc+3gxCkyVR3cTSXE/n5BEGf8aOgBpepULWa1RZfx"
           "YHY14PlKULDygdXSdrrR2kNSwoKz/Oo4d+3EE92L7ocl1+djZbptzgWgtw1OseLwbFik+iKlIdqPsH+IUQvX7yV545ZQtAP8Qj1R+uCqkw=="
           " test@test")


class AdminAccountRowTests(TestCase):
    def setUp(self):
        from computes.models import Compute
        from instances.models import Instance

        self.admin = get_user_model().objects.create_superuser("audit-admin", "audit@example.com", "pw")
        self.bob = get_user_model().objects.create_user("bob", password="Bob-pass-2026")
        compute = Compute.objects.create(name="c1", hostname="127.0.0.1", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="vm", uuid="66666666-6666-6666-6666-666666666666")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()  # the login's row

    def test_ownership_from_the_accounts_pages(self):
        from accounts.models import UserInstance

        self.client.post(reverse("accounts:user_instance_create", args=[self.bob.pk]),
                         {"user": self.bob.pk, "instance": self.vm.pk})
        ui = UserInstance.objects.get(user=self.bob, instance=self.vm)
        url = reverse("accounts:user_instance_update", args=[ui.pk])
        self.client.post(url, {"is_vnc": "on"})
        self.client.post(url, {"is_vnc": "on"})  # no change
        self.client.post(reverse("accounts:user_instance_delete", args=[ui.pk]))
        self.assertEqual(rows(), [
            ("VM vm: add owner bob", True),
            ("VM vm: change owner bob: is_vnc", True),
            ("VM vm: remove owner bob", True),
        ])
        self.assertEqual(set(Logs.objects.values_list("user", "host", "instance", "instance_uuid")),
                         {("audit-admin", "c1", "vm", self.vm.uuid)})

    def test_otp_mail_without_an_email(self):
        from smtplib import SMTPException
        from unittest.mock import patch

        from django_otp.plugins.otp_totp.models import TOTPDevice

        url = reverse("accounts:admin_email_otp", args=[self.bob.pk])
        with patch("accounts.views.send_email_with_otp") as send:
            self.client.post(url)
            send.assert_not_called()
        self.assertFalse(TOTPDevice.objects.filter(user=self.bob).exists())

        self.bob.email = "bob@example.com"
        self.bob.save()
        with patch("accounts.views.send_email_with_otp") as send:
            self.client.post(url)
            send.assert_called_once()
        with patch("accounts.views.send_email_with_otp", side_effect=SMTPException("refused")), \
                self.assertRaises(SMTPException):
            self.client.post(url)
        self.assertEqual(rows(), [
            ("User bob: mail OTP QR code: no email address", False),
            ("User bob: mail OTP QR code", True),
            ("User bob: mail OTP QR code: SMTPException", False),
        ])

    def test_ssh_keys(self):
        from accounts.models import UserSSHKey

        self.client.post(reverse("accounts:ssh_key_create"), {"keyname": "laptop", "keypublic": SSH_KEY})
        key = UserSSHKey.objects.get(keyname="laptop")
        self.client.post(reverse("accounts:ssh_key_delete", args=[key.pk]))
        self.assertEqual(rows(), [("SSH key laptop: add", True), ("SSH key laptop: delete", True)])
        self.assertFalse(Logs.objects.filter(message__contains="AAAA").exists())
