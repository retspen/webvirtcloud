"""A user's SSH keys: they go with the user, and a key is valid with or without a comment."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserSSHKey
from accounts.utils import validate_ssh_key


class SshKeyTestCase(TestCase):
    def test_ssh_key_cascade_deletion(self):
        user = get_user_model().objects.create_user(username="sec_acc_user", password="password")
        key = UserSSHKey.objects.create(
            user=user,
            keyname="my-key",
            keypublic="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGabcdef123456 test@example.com",
        )
        self.assertTrue(UserSSHKey.objects.filter(id=key.id).exists())

        # When user is deleted, key should be deleted via CASCADE (not left orphan)
        user.delete()
        self.assertFalse(UserSSHKey.objects.filter(id=key.id).exists())

    def test_validate_ssh_key_supports_keys_with_and_without_comment(self):
        rsa_base = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC6OOdbfv27QVnSC6sKxGaHb6YFc+3gxCkyVR3cTSXE/n5BEGf8aOgBpepULWa1RZfxYHY14PlKULDygdXSdrrR2kNSwoKz/Oo4d+3EE92L7ocl1+djZbptzgWgtw1OseLwbFik+iKlIdqPsH+IUQvX7yV545ZQtAP8Qj1R+uCqkw=="
        # Key with comment
        key_with_comment = f"{rsa_base} test@test"
        self.assertTrue(validate_ssh_key(key_with_comment))

        # Key without comment
        key_without_comment = rsa_base
        self.assertTrue(validate_ssh_key(key_without_comment))

        # Invalid key
        self.assertFalse(validate_ssh_key("not a valid key string"))
