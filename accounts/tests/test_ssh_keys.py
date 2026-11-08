"""A user's SSH keys go with the user (validate_ssh_key: test_utils)."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserSSHKey


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

