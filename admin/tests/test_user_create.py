"""Creating a user in the admin pages: the password reaches the database only
hashed, and the configured password validators apply as on the change forms."""

import re

from django.contrib.auth.models import Group, Permission, User
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance

RAW = "Raw-Passw0rd-in-the-form"
LIMITS = {"role": "user", "max_instances": 1, "max_cpus": 1, "max_memory": 1, "max_disk_size": 4}


class UserCreateTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("uc-admin", "uc@example.com", "pw"))
        self.change_password = Permission.objects.get(content_type__app_label="accounts", codename="change_password")

    def create(self, **data):
        return self.client.post(reverse("admin:user_create"), {"username": "newbie", "password": RAW, **LIMITS, **data})

    def test_the_raw_password_is_never_written(self):
        written = []

        def record(execute, sql, params, many, context):
            if RAW in repr(params):
                written.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(record):
            response = self.create()
        self.assertRedirects(response, reverse("admin:user_list"))
        self.assertEqual(written, [])
        self.assertTrue(User.objects.get(username="newbie").check_password(RAW))

    def test_a_new_user_may_change_the_password_and_open_consoles_unless_unticked(self):
        # new VMs have a VNC password, which the console page sends only with passwordless_console
        page = self.client.get(reverse("admin:user_create")).content.decode()
        ticked = set(re.findall(r'<input[^>]*name="user_permissions"[^>]*value="(\d+)"[^>]*checked', page))
        self.assertEqual(ticked, {str(self.change_password.pk), str(Permission.objects.get(codename="passwordless_console").pk)})

    def test_permissions_are_named_in_the_users_language(self):
        # the database keeps each permission's English name
        page = self.client.get(reverse("admin:user_create"), HTTP_ACCEPT_LANGUAGE="tr").content.decode()
        for name in ("Parola değiştirebilir", "Sanal makineleri klonlayabilir", "Parolasız konsol erişimi yapabilir",
                     "Sanal makinelerin anlık görüntüsünü alabilir", "Sanal makineleri görebilir"):
            self.assertIn(name, page)
        self.assertNotIn("Can clone instances", page)

    def test_groups_and_permissions_are_saved(self):
        group = Group.objects.create(name="uc-group")
        self.create(groups=[group.pk], user_permissions=[self.change_password.pk])
        user = User.objects.get(username="newbie")
        self.assertEqual(list(user.groups.all()), [group])
        self.assertEqual(list(user.user_permissions.all()), [self.change_password])

    def test_an_unticked_permission_stays_off(self):
        self.create()
        self.assertFalse(User.objects.get(username="newbie").user_permissions.exists())

    @override_settings(
        AUTH_PASSWORD_VALIDATORS=[
            {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 30}}
        ]
    )
    def test_configured_password_validators_apply(self):
        response = self.create()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least 30 characters")
        self.assertFalse(User.objects.filter(username="newbie").exists())

    @override_settings(
        AUTH_PASSWORD_VALIDATORS=[{"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"}]
    )
    def test_the_password_is_checked_against_the_new_username(self):
        response = self.client.post(
            reverse("admin:user_create"), {"username": "rumpelstiltskin", "password": "rumpelstiltskin1", **LIMITS}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "too similar to the username")


class DefaultInstancesTests(TestCase):
    """NEW_USER_DEFAULT_INSTANCES names VMs, and a name may repeat across hosts."""

    def setUp(self):
        self.client.force_login(User.objects.create_superuser("uc-admin", "uc@example.com", "pw"))
        one, two = (Compute.objects.create(name=name, hostname="localhost", login="", password="", details="", type=4)
                    for name in ("uc-one", "uc-two"))
        self.web = Instance.objects.create(compute=one, name="web", uuid="00000000-0000-0000-0000-000000000001")
        for compute, uuid in ((one, "00000000-0000-0000-0000-000000000002"), (two, "00000000-0000-0000-0000-000000000003")):
            Instance.objects.create(compute=compute, name="db", uuid=uuid)

    def create(self):
        return self.client.post(reverse("admin:user_create"), {"username": "newbie", "password": RAW, **LIMITS})

    @override_settings(NEW_USER_DEFAULT_INSTANCES=["web"])
    def test_the_new_user_owns_the_named_vm(self):
        self.assertRedirects(self.create(), reverse("admin:user_list"))
        self.assertEqual([o.instance for o in UserInstance.objects.filter(user__username="newbie")], [self.web])

    @override_settings(NEW_USER_DEFAULT_INSTANCES=["web"])
    def test_an_owned_vm_is_not_given_a_second_owner_when_one_is_allowed(self):
        from appsettings.models import AppSettings

        UserInstance.objects.create(user=User.objects.create_user("alice"), instance=self.web)
        AppSettings.objects.filter(key="ALLOW_INSTANCE_MULTIPLE_OWNER").update(value="False")
        self.assertContains(self.create(), "NEW_USER_DEFAULT_INSTANCES: web has an owner, and only one is allowed")
        self.assertFalse(User.objects.filter(username="newbie").exists())
        AppSettings.objects.filter(key="ALLOW_INSTANCE_MULTIPLE_OWNER").update(value="True")
        self.assertRedirects(self.create(), reverse("admin:user_list"))
        self.assertEqual(UserInstance.objects.filter(instance=self.web).count(), 2)

    def test_a_name_that_is_not_one_vm_is_refused_on_the_form(self):
        for name in ("no-such-vm", "db"):
            with self.subTest(name), override_settings(NEW_USER_DEFAULT_INSTANCES=["web", name]):
                response = self.create()
                self.assertContains(response, f"NEW_USER_DEFAULT_INSTANCES: {name} is not exactly one VM")
                self.assertFalse(User.objects.filter(username="newbie").exists())
