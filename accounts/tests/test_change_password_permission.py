"""Who may change their own password is the change_password permission: new
users get it, admins may take it away, and later migrate runs keep their choice."""

import importlib
from unittest.mock import MagicMock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from admin.forms import UserCreateForm

migration = importlib.import_module("accounts.migrations.0008_apply_show_profile_edit_password_once")


def permission():
    return Permission.objects.get(content_type__app_label="accounts", codename="change_password")


def can_change(user):
    return get_user_model().objects.get(pk=user.pk).has_perm("accounts.change_password")


class ChangePasswordPermissionTestCase(TestCase):
    def test_new_users_may_change_their_password(self):
        self.assertTrue(can_change(get_user_model().objects.create_user("new", password="pw")))

    def test_user_without_the_permission_cannot_open_the_page(self):
        user = get_user_model().objects.create_user("limited", password="pw")
        user.user_permissions.remove(permission())
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:change_password")).status_code, 403)

    def test_a_user_without_a_local_password_cannot_change_it(self):
        user = get_user_model().objects.create_user("ldap-user")  # as django-auth-ldap makes them
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:change_password")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("accounts:profile")), reverse("accounts:change_password"))

    def test_create_form_ticks_it_and_the_admin_choice_wins(self):
        self.assertIn(permission(), UserCreateForm().fields["user_permissions"].initial)
        form = UserCreateForm(data={"username": "unticked", "password": "pw", "is_active": True})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(can_change(form.save()))

    @override_settings(SHOW_PROFILE_EDIT_PASSWORD=True)
    def test_migrate_keeps_a_removed_permission(self):
        user = get_user_model().objects.create_user("kept", password="pw")
        user.user_permissions.remove(permission())

        call_command("migrate", verbosity=0)

        self.assertFalse(can_change(user))


class ApplySettingOnceTestCase(TestCase):
    def run_migration(self):
        migration.apply_setting_once(apps, MagicMock(connection=MagicMock(alias="default")))

    def setUp(self):
        self.with_perm = get_user_model().objects.create_user("with", password="pw")
        self.without = get_user_model().objects.create_user("without", password="pw")
        self.without.user_permissions.remove(permission())

    @override_settings(SHOW_PROFILE_EDIT_PASSWORD=True)
    def test_true_grants_to_everyone(self):
        self.run_migration()
        self.assertTrue(can_change(self.with_perm) and can_change(self.without))

    @override_settings(SHOW_PROFILE_EDIT_PASSWORD=False)
    def test_false_revokes_from_everyone(self):
        self.run_migration()
        self.assertFalse(can_change(self.with_perm) or can_change(self.without))

    def test_without_the_setting_nothing_changes(self):
        with self.settings():
            from django.conf import settings

            if hasattr(settings, "SHOW_PROFILE_EDIT_PASSWORD"):
                del settings.SHOW_PROFILE_EDIT_PASSWORD
            self.run_migration()
        self.assertTrue(can_change(self.with_perm))
        self.assertFalse(can_change(self.without))
