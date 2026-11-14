"""The generated admin password must be replaced at first login."""
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from accounts.models import UserAttributes

GENERATED = "Generated-Pass-123"


class FirstLoginPasswordChangeTestCase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.password_file = Path(self.tmp.name) / "data" / "admin_password"
        self.password_file.parent.mkdir()
        self.password_file.write_text(GENERATED + "\n")
        settings_override = override_settings(BASE_DIR=Path(self.tmp.name))
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.admin = get_user_model().objects.create_superuser(
            username="firstadmin", email="firstadmin@example.com", password=GENERATED
        )
        UserAttributes.objects.create(user=self.admin, must_change_password=True)

    def test_login_with_generated_password_redirects_every_page_to_change_form(self):
        self.client.login(request=RequestFactory().get("/"), username="firstadmin", password=GENERATED)
        for url in (reverse("index"), reverse("instances:index"), reverse("accounts:profile")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response, reverse("accounts:change_password"), fetch_redirect_response=False
                )
        self.assertEqual(self.client.get(reverse("accounts:change_password")).status_code, 200)

    def test_an_api_request_of_the_session_gets_json_not_the_form(self):
        # as a token of that user does (accounts.auth)
        self.client.login(request=RequestFactory().get("/"), username="firstadmin", password=GENERATED)
        response = self.client.get("/api/v1/instances/")
        self.assertEqual((response.status_code, response.json()), (403, {"detail": "Change your password before using the API."}))

    def test_changing_the_password_lifts_the_redirect_and_deletes_the_file(self):
        self.client.login(request=RequestFactory().get("/"), username="firstadmin", password=GENERATED)
        self.client.post(
            reverse("accounts:change_password"),
            {
                "old_password": GENERATED,
                "new_password1": "A-new-strong-pass-456",
                "new_password2": "A-new-strong-pass-456",
            },
        )
        self.assertFalse(self.password_file.exists())
        self.assertFalse(UserAttributes.objects.get(user=self.admin).must_change_password)
        response = self.client.get(reverse("instances:index"))
        self.assertEqual(response.status_code, 200)

    def test_user_with_another_password_is_not_forced(self):
        get_user_model().objects.create_superuser(
            username="otheradmin", email="otheradmin@example.com", password="Other-pass-789"
        )
        self.client.login(request=RequestFactory().get("/"), username="otheradmin", password="Other-pass-789")
        self.assertEqual(self.client.get(reverse("instances:index")).status_code, 200)
        self.assertTrue(self.password_file.exists())

    def test_missing_file_and_a_new_session_do_not_bypass_enforcement(self):
        self.password_file.unlink()
        self.client.force_login(self.admin)
        self.assertRedirects(
            self.client.get(reverse("accounts:profile")),
            reverse("accounts:change_password"), fetch_redirect_response=False,
        )

    def test_unreadable_password_file_is_not_used_during_login(self):
        with patch("accounts.apps.admin_password_path", side_effect=AssertionError("must not read file")):
            self.client.login(request=RequestFactory().get("/"), username="firstadmin", password=GENERATED)
        self.assertRedirects(
            self.client.get(reverse("accounts:profile")),
            reverse("accounts:change_password"), fetch_redirect_response=False,
        )

    def test_cleanup_failure_does_not_undo_a_successful_password_change(self):
        self.client.force_login(self.admin)
        with patch("accounts.views.os.remove", side_effect=PermissionError("read-only")):
            response = self.client.post(reverse("accounts:change_password"), {
                "old_password": GENERATED, "new_password1": "A-new-strong-pass-456",
                "new_password2": "A-new-strong-pass-456",
            })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserAttributes.objects.get(user=self.admin).must_change_password)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("A-new-strong-pass-456"))
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 200)

    def test_missing_middleware_is_reported_by_the_upgrade_check(self):
        from accounts.checks import password_change_middleware_check
        with override_settings(MIDDLEWARE=["django.contrib.auth.middleware.AuthenticationMiddleware"]):
            errors = password_change_middleware_check(None)
        self.assertEqual([error.id for error in errors], ["accounts.E001"])

    def test_legacy_migration_flags_only_the_matching_account(self):
        import importlib
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        migration = importlib.import_module("accounts.migrations.0007_userattributes_must_change_password")
        UserAttributes.objects.filter(user=self.admin).update(must_change_password=False)
        other = get_user_model().objects.create_superuser("legacy_other", "", "other-password")
        migration.flag_legacy_generated_password(apps, SimpleNamespace(connection=connection))
        self.assertTrue(UserAttributes.objects.get(user=self.admin).must_change_password)
        self.assertFalse(UserAttributes.objects.filter(user=other, must_change_password=True).exists())

    def test_legacy_migration_fails_if_password_file_cannot_be_read(self):
        import importlib
        migration = importlib.import_module("accounts.migrations.0007_userattributes_must_change_password")
        with patch("pathlib.Path.read_text", side_effect=PermissionError("unreadable")):
            with self.assertRaisesRegex(RuntimeError, "run migrate as its owner"):
                migration.flag_legacy_generated_password(None, None)


class DefaultAdminPasswordMigrationTestCase(TestCase):
    """An installation of a version up to v2.0.0 still signed in as admin/admin."""

    def admin_with(self, password):
        admin, _ = get_user_model().objects.get_or_create(username="admin", defaults={"is_superuser": True})
        admin.set_password(password)
        admin.save()
        UserAttributes.objects.filter(user=admin).delete()  # the migration also makes them
        return admin

    def migrate(self):
        import importlib
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        migration = importlib.import_module("accounts.migrations.0013_default_admin_password")
        migration.flag_default_admin_password(apps, SimpleNamespace(connection=connection))

    def test_the_default_admin_password_must_be_changed(self):
        admin = self.admin_with("admin")
        self.migrate()
        self.assertTrue(UserAttributes.objects.get(user=admin).must_change_password)
        self.client.force_login(admin)
        self.assertRedirects(self.client.get(reverse("instances:index")), reverse("accounts:change_password"),
                             fetch_redirect_response=False)

    def test_a_changed_admin_password_is_left_alone(self):
        admin = self.admin_with("Changed-pw-2026")
        UserAttributes.objects.create(user=admin)
        self.migrate()
        self.assertFalse(UserAttributes.objects.get(user=admin).must_change_password)
