from unittest.mock import PropertyMock, patch

from appsettings.models import AppSettings
from appsettings.settings import app_settings
from computes.models import Compute
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.shortcuts import reverse
from django.test import Client, RequestFactory, TestCase, override_settings
from instances.models import Instance
from libvirt import libvirtError


from accounts.forms import UserInstanceForm, UserSSHKeyForm
from accounts.models import UserInstance, UserSSHKey
from accounts.utils import validate_ssh_key


class AccountsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_user = User.objects.create_superuser("accounts-admin", "admin@example.com", "pw")
        cls.test_user = User.objects.create_user(username="test", password="test")

        # Add compute
        cls.compute = Compute.objects.create(
            name="accounts-test-compute",
            hostname="localhost",
            login="",
            password="",
            details="local",
            type=4,
        )
        cls.instance = Instance.objects.create(
            compute=cls.compute,
            name="test-vm",
        )

    def setUp(self):
        # the pages read no host: its compute is not there
        down = patch.object(Compute, "connection", new_callable=PropertyMock, return_value=libvirtError("unreachable"))
        down.start()
        self.addCleanup(down.stop)
        self.client.force_login(self.admin_user)
        permission = Permission.objects.get(codename="change_password")
        self.test_user.user_permissions.add(permission)
        self.rsa_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC6OOdbfv27QVnSC6sKxGaHb6YFc+3gxCkyVR3cTSXE/n5BEGf8aOgBpepULWa1RZfxYHY14PlKULDygdXSdrrR2kNSwoKz/Oo4d+3EE92L7ocl1+djZbptzgWgtw1OseLwbFik+iKlIdqPsH+IUQvX7yV545ZQtAP8Qj1R+uCqkw== test@test"
        self.ecdsa_key = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBJc5xpT3R0iFJYNZbmWgAiDlHquX/BcV1kVTsnBfiMsZgU3lGaqz2eb7IBcir/dxGnsVENTTmPQ6sNcxLxT9kkQ= realgecko@archlinux"

    def test_profile(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse("accounts:account", args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(OTP_ENABLED=True)
    def test_account_with_otp(self):
        response = self.client.get(
            reverse("accounts:account", args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_login_logout(self):
        client = Client()

        response = client.post(
            reverse("accounts:login"), {"username": "test", "password": "test"}
        )
        self.assertRedirects(response, settings.LOGIN_REDIRECT_URL)

        response = client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))

    def test_a_signed_in_user_is_sent_on_from_the_login_page(self):
        self.client.force_login(self.test_user)
        login = reverse("accounts:login")
        response = self.client.get(f"{login}?next={reverse('computes')}")
        self.assertRedirects(response, reverse("computes"), fetch_redirect_response=False)
        response = self.client.get(f"{login}?next=https://example.com/")
        self.assertRedirects(response, settings.LOGIN_REDIRECT_URL, fetch_redirect_response=False)

    def test_change_password(self):
        self.client.force_login(self.test_user)

        response = self.client.get(reverse("accounts:change_password"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:change_password"),
            {
                "old_password": "wrongpass",
                "new_password1": "Wvc-changed-9",
                "new_password2": "Wvc-changed-9",
            },
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:change_password"),
            {
                "old_password": "test",
                "new_password1": "Wvc-changed-9",
                "new_password2": "Wvc-changed-9",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))

        self.client.logout()

        logged_in = self.client.login(request=RequestFactory().get("/"), username="test", password="Wvc-changed-9")
        self.assertTrue(logged_in)

    def test_user_instance_create_update_delete(self):
        # create
        response = self.client.get(
            reverse("accounts:user_instance_create", args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:user_instance_create", args=[self.test_user.id]),
            {
                "user": self.test_user.id,
                "instance": self.instance.id,
                "is_change": False,
                "is_delete": False,
                "is_vnc": False,
            },
        )
        self.assertRedirects(
            response, reverse("accounts:account", args=[self.test_user.id])
        )

        user_instance: UserInstance = UserInstance.objects.get(
            user=self.test_user, instance=self.instance
        )
        self.assertEqual(user_instance.user, self.test_user)
        self.assertEqual(user_instance.instance, self.instance)
        self.assertEqual(user_instance.is_change, False)
        self.assertEqual(user_instance.is_delete, False)
        self.assertEqual(user_instance.is_vnc, False)

        # update
        response = self.client.get(
            reverse("accounts:user_instance_update", args=[user_instance.id])
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:user_instance_update", args=[user_instance.id]),
            {
                "user": self.test_user.id,
                "instance": self.instance.id,
                "is_change": True,
                "is_delete": True,
                "is_vnc": True,
            },
        )
        self.assertRedirects(
            response, reverse("accounts:account", args=[self.test_user.id])
        )

        user_instance = UserInstance.objects.get(
            user=self.test_user, instance=self.instance
        )
        self.assertEqual(user_instance.user, self.test_user)
        self.assertEqual(user_instance.instance, self.instance)
        self.assertEqual(user_instance.is_change, True)
        self.assertEqual(user_instance.is_delete, True)
        self.assertEqual(user_instance.is_vnc, True)

        # delete
        response = self.client.get(
            reverse("accounts:user_instance_delete", args=[user_instance.id])
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:user_instance_delete", args=[user_instance.id])
        )
        self.assertRedirects(
            response, reverse("accounts:account", args=[self.test_user.id])
        )

        # test 'next' redirect during deletion
        user_instance = UserInstance.objects.create(
            user=self.test_user, instance=self.instance
        )
        response = self.client.post(
            reverse("accounts:user_instance_delete", args=[user_instance.id])
            + "?next="
            + reverse("index")
        )
        self.assertRedirects(response, reverse("index"))

    def test_update_user_profile(self):
        self.client.force_login(self.test_user)

        user = get_user_model().objects.get(username="test")
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.last_name, "")
        self.assertEqual(user.email, "")

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "first name",
                "last_name": "last name",
                "email": "email@mail.mail",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))

        user = get_user_model().objects.get(username="test")
        self.assertEqual(user.first_name, "first name")
        self.assertEqual(user.last_name, "last name")
        self.assertEqual(user.email, "email@mail.mail")

    def test_create_delete_ssh_key(self):
        response = self.client.get(reverse("accounts:ssh_key_create"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:ssh_key_create"),
            {
                "keyname": "keyname",
                "keypublic": self.rsa_key,
            },
        )
        self.assertRedirects(response, reverse("accounts:profile") + "#sshkeys")

        key = UserSSHKey.objects.get(keyname="keyname")
        self.assertEqual(key.keyname, "keyname")
        self.assertEqual(key.keypublic, self.rsa_key)

        response = self.client.get(reverse("accounts:ssh_key_delete", args=[key.id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("accounts:ssh_key_delete", args=[key.id]))
        self.assertRedirects(response, reverse("accounts:profile") + "#sshkeys")

    def test_the_profile_lists_keys_and_tokens_where_links_land(self):
        admin = self.admin_user
        key = UserSSHKey.objects.create(user=admin, keyname="laptop", keypublic=self.rsa_key)
        response = self.client.get(reverse("accounts:profile"))
        # other pages link to #sshkeys and #apitokens
        self.assertContains(response, 'id="sshkeys"')
        self.assertContains(response, 'id="apitokens"')
        self.assertContains(response, f'href="{reverse("accounts:ssh_key_delete", args=[key.id])}"')
        self.assertContains(response, f'href="{reverse("accounts:change_password")}"')
        # an LDAP user's password is changed in LDAP
        admin.set_unusable_password()
        admin.save()
        self.client.force_login(admin)
        self.assertNotContains(self.client.get(reverse("accounts:profile")), f'href="{reverse("accounts:change_password")}"')

    def test_validate_ssh_key(self):
        self.assertFalse(validate_ssh_key(""))
        self.assertFalse(validate_ssh_key("ssh-rsa ABBA test@test"))
        self.assertFalse(validate_ssh_key("ssh-rsa AAAABwdzZGY= test@test"))
        self.assertFalse(validate_ssh_key("ssh-rsa AAA test@test"))
        # validate ecdsa key
        self.assertTrue(validate_ssh_key(self.ecdsa_key))

    def test_forms(self):
        # raise available validation errors for maximum coverage
        form = UserSSHKeyForm(
            {"keyname": "keyname", "keypublic": self.rsa_key}, user=self.test_user
        )
        form.save()

        form = UserSSHKeyForm(
            {"keyname": "keyname", "keypublic": self.rsa_key}, user=self.test_user
        )
        self.assertFalse(form.is_valid())

        form = UserSSHKeyForm(
            {"keyname": "keyname", "keypublic": "invalid key"}, user=self.test_user
        )
        self.assertFalse(form.is_valid())

        self.addCleanup(setattr, app_settings, "ALLOW_INSTANCE_MULTIPLE_OWNER", app_settings.ALLOW_INSTANCE_MULTIPLE_OWNER)
        app_settings.ALLOW_INSTANCE_MULTIPLE_OWNER = "False"
        form = UserInstanceForm(
            {
                "user": self.admin_user.id,
                "instance": self.instance.id,
                "is_change": False,
                "is_delete": False,
                "is_vnc": False,
            }
        )
        form.save()
        form = UserInstanceForm(
            {
                "user": self.test_user.id,
                "instance": self.instance.id,
                "is_change": False,
                "is_delete": False,
                "is_vnc": False,
            }
        )
        self.assertFalse(form.is_valid())


class SingleOwnerEditTests(TestCase):
    """With one owner per VM, the owner's own rights can still be changed."""

    def test_the_only_owner_is_edited(self):
        AppSettings.objects.filter(key="ALLOW_INSTANCE_MULTIPLE_OWNER").update(value="False")
        admin = get_user_model().objects.create_superuser("audit-admin", "audit@example.com", "pw")
        bob = get_user_model().objects.create_user("bob")
        compute = Compute.objects.create(name="c1", hostname="127.0.0.1", login="", password="", type=4)
        vm = Instance.objects.create(compute=compute, name="vm", uuid="99999999-9999-9999-9999-999999999999")
        ui = UserInstance.objects.create(user=bob, instance=vm)
        self.client.force_login(admin)
        response = self.client.post(reverse("accounts:user_instance_update", args=[ui.pk]), {"is_vnc": "on"})
        self.assertRedirects(response, reverse("accounts:account", args=[bob.pk]), fetch_redirect_response=False)
        ui.refresh_from_db()
        self.assertTrue(ui.is_vnc)


class OwnerRightsReturnTestCase(TestCase):
    """Edit rights on a VM's Users tab comes back to that tab; a page of
    another site does not count."""

    def test_an_owner_s_rights_come_back_to_the_vm_page(self):
        admin = get_user_model().objects.create_superuser("rights-admin", "rights@example.com", "x")
        owner = get_user_model().objects.create_user("rights-owner")
        compute = Compute.objects.create(name="rights", hostname="192.0.2.30", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="rights-vm", uuid="12121212-0000-0000-0000-000000000000")
        user_instance = UserInstance.objects.create(user=owner, instance=vm)
        self.client.force_login(admin)
        update = reverse("accounts:user_instance_update", args=[user_instance.id])
        for next_url, back in ((f"/instances/{vm.id}/%23users", f"/instances/{vm.id}/#users"),
                               ("https://example.com/", reverse("accounts:account", args=[owner.id]))):
            with self.subTest(next_url):
                response = self.client.post(f"{update}?next={next_url}", {"is_change": True})
                self.assertRedirects(response, back, fetch_redirect_response=False)


class UserInstanceDeleteTestCase(TestCase):
    def test_open_redirect_prevented_in_user_instance_delete(self):
        User = get_user_model()
        admin = User.objects.create_superuser(username="sec_acc_admin", email="admin@example.com", password="password")
        user = User.objects.create_user(username="sec_acc_user", password="password")
        compute = Compute.objects.create(name="acc-comp", hostname="127.0.0.1", login="root", type=1)
        instance = Instance.objects.create(compute=compute, name="acc-vm", uuid="99999999-9999-9999-9999-999999999999")
        user_inst = UserInstance.objects.create(instance=instance, user=user)
        self.client.force_login(admin)
        url = reverse("accounts:user_instance_delete", args=[user_inst.id])

        # Attempt external malicious redirect
        res = self.client.post(f"{url}?next=https://malicious-attacker.com")
        self.assertEqual(res.status_code, 302)
        # Should redirect to safe internal URL (user account page), NOT external site
        self.assertNotIn("malicious-attacker.com", res.url)
        self.assertEqual(res.url, reverse("accounts:account", args=[user.id]))
