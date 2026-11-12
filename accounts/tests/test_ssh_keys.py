"""A user's SSH keys go with the user, and a key is added once
(validate_ssh_key: test_utils)."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import UserSSHKeyForm
from accounts.models import UserSSHKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


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


    def test_the_same_key_with_another_comment_is_refused(self):
        user = get_user_model().objects.create_user(username="dup_key_user", password="password")
        key = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
        UserSSHKey.objects.create(user=user, keyname="laptop", keypublic=f"{key} laptop")
        form = UserSSHKeyForm({"keyname": "desktop", "keypublic": f"{key}  other comment"}, user=user)
        self.assertEqual(form.errors["keypublic"], ["Public key already exist"])
