from appsettings.settings import app_settings
from computes.models import Compute
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.shortcuts import reverse
from django.test import Client, TestCase
from instances.models import Instance
from instances.utils import refr
from libvirt import VIR_DOMAIN_UNDEFINE_NVRAM
from vrtManager.create import wvmCreate

from accounts.forms import UserInstanceForm, UserSSHKeyForm
from accounts.models import UserInstance, UserSSHKey
from accounts.utils import validate_ssh_key


class AccountsTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Add users for testing purposes
        User = get_user_model()
        cls.admin_user = User.objects.get(pk=1)
        cls.test_user = User.objects.create_user(username="test", password="test")

        # Add localhost compute
        cls.compute = Compute(
            name="test-compute",
            hostname="localhost",
            login="",
            password="",
            details="local",
            type=4,
        )
        cls.compute.save()

        cls.connection = wvmCreate(
            cls.compute.hostname,
            cls.compute.login,
            cls.compute.password,
            cls.compute.type,
        )

        # Add disks for testing
        cls.connection.create_volume(
            "default",
            "test-volume",
            1,
            "qcow2",
            False,
            0,
            0,
        )

        # XML for testing vm
        with open("conf/test-vm.xml", "r") as f:
            cls.xml = f.read()

        # Create testing vm from XML
        cls.connection._defineXML(cls.xml)
        refr(cls.compute)
        cls.instance = Instance.objects.get(pk=1)

    @classmethod
    def tearDownClass(cls):
        # Destroy testing vm
        cls.instance.proxy.delete_all_disks()
        cls.instance.proxy.delete(VIR_DOMAIN_UNDEFINE_NVRAM)
        super().tearDownClass()

    def setUp(self):
        self.client.login(username="admin", password="admin")
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

    def test_account_with_otp(self):
        settings.OTP_ENABLED = True
        response = self.client.get(
            reverse("accounts:account", args=[self.test_user.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_login_logout(self):
        client = Client()

        response = client.post(
            reverse("accounts:login"), {"username": "test", "password": "test"}
        )
        self.assertRedirects(response, reverse("accounts:profile"))

        response = client.get(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))

    def test_change_password(self):
        self.client.force_login(self.test_user)

        response = self.client.get(reverse("accounts:change_password"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:change_password"),
            {
                "old_password": "wrongpass",
                "new_password1": "newpw",
                "new_password2": "newpw",
            },
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("accounts:change_password"),
            {
                "old_password": "test",
                "new_password1": "newpw",
                "new_password2": "newpw",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))

        self.client.logout()

        logged_in = self.client.login(username="test", password="newpw")
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

        user_instance: UserInstance = UserInstance.objects.get(pk=1)
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

        user_instance: UserInstance = UserInstance.objects.get(pk=1)
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
        self.assertRedirects(response, reverse("accounts:profile"))

        key = UserSSHKey.objects.get(pk=1)
        self.assertEqual(key.keyname, "keyname")
        self.assertEqual(key.keypublic, self.rsa_key)

        response = self.client.get(reverse("accounts:ssh_key_delete", args=[1]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("accounts:ssh_key_delete", args=[1]))
        self.assertRedirects(response, reverse("accounts:profile"))

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
