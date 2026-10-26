"""A superuser's page of a user: the VMs and their permissions, the SSH keys."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance, UserSSHKey
from computes.models import Compute
from instances.models import Instance
from logs.models import Logs

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGbXMJlKTOlUOvwzdjDs3ac3ivHQoOxAUZEwi3WsJHfs alice@example"


class AccountPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("ap-admin", "ap@example.com", "pw")
        self.alice = User.objects.create_user("alice", password="pw")
        self.key = UserSSHKey.objects.create(user=self.alice, keyname="laptop", keypublic=KEY)
        self.client.force_login(self.admin)

    def page(self):
        return self.client.get(reverse("accounts:account", args=[self.alice.pk]))

    def test_the_permissions_are_marks_not_true_or_false(self):
        compute = Compute.objects.create(name="ap-host", hostname="localhost", login="", password="", details="", type=4)
        vm = Instance.objects.create(compute=compute, name="ap-vm", uuid="00000000-0000-0000-0000-000000000001")
        UserInstance.objects.create(user=self.alice, instance=vm, is_vnc=True, is_change=False, is_delete=False)
        response = self.page()
        self.assertContains(response, "ap-vm")
        self.assertNotContains(response, "<td>True</td>", html=True)
        self.assertNotContains(response, "<td>False</td>", html=True)

    def test_a_user_without_vms_is_told_so(self):
        self.assertContains(self.page(), "No VMs.")

    def test_a_superuser_deletes_a_users_key(self):
        url = reverse("accounts:account_ssh_key_delete", args=[self.alice.pk, self.key.pk])
        self.assertContains(self.page(), f'href="{url}"')
        self.assertContains(self.client.get(url), "laptop")
        response = self.client.post(url)
        self.assertRedirects(response, reverse("accounts:account", args=[self.alice.pk]) + "#public-keys",
                             fetch_redirect_response=False)
        self.assertFalse(UserSSHKey.objects.exists())
        self.assertTrue(Logs.objects.filter(message="SSH key laptop of alice: delete").exists())

    def test_only_a_superuser_and_only_that_users_key(self):
        bob = User.objects.create_user("bob", password="pw")
        self.assertEqual(self.client.post(reverse("accounts:account_ssh_key_delete", args=[bob.pk, self.key.pk])).status_code, 404)
        self.client.force_login(bob)
        url = reverse("accounts:account_ssh_key_delete", args=[self.alice.pk, self.key.pk])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(UserSSHKey.objects.exists())
