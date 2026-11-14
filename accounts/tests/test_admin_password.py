"""The generated admin password must not be printed to the log."""
import io
import os
import stat
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.contrib.auth import authenticate, get_user_model
from django.test import RequestFactory, TestCase, override_settings

from accounts.apps import create_admin
from accounts.models import UserAttributes


class GeneratedAdminPasswordTestCase(TestCase):
    def _run_create_admin(self, base_dir, plan=None):
        get_user_model().objects.all().delete()
        if plan is None:
            migration = MagicMock(app_label="accounts")
            migration.name = "0001_initial"
            plan = [(migration, False)]
        out = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k not in ("ADMIN_PASSWORD", "ADMIN_USERNAME")}
        with override_settings(BASE_DIR=Path(base_dir)), patch.dict(
            os.environ, env, clear=True
        ), redirect_stdout(out):
            create_admin(sender=None, plan=plan, apps=apps)
        return out.getvalue()

    def test_password_is_written_to_a_private_file_not_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            output = self._run_create_admin(tmp)
            password_file = Path(tmp) / "data" / "admin_password"

            self.assertTrue(password_file.exists())
            password = password_file.read_text().strip()
            self.assertEqual(stat.S_IMODE(password_file.stat().st_mode), 0o600)
            self.assertNotIn(password, output)
            self.assertIn(str(password_file), output)
            self.assertIsNotNone(authenticate(RequestFactory().get("/"), username="admin", password=password))
            self.assertTrue(UserAttributes.objects.get(user__username="admin").must_change_password)

    def test_does_not_follow_a_planted_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            victim = Path(tmp) / "victim"
            victim.write_text("original\n")
            (Path(tmp) / "data" / "admin_password").symlink_to(victim)

            self._run_create_admin(tmp)

            password_file = Path(tmp) / "data" / "admin_password"
            self.assertEqual(victim.read_text(), "original\n")
            self.assertFalse(password_file.is_symlink())
            self.assertEqual(stat.S_IMODE(password_file.stat().st_mode), 0o600)

    def test_storage_failure_does_not_print_password_or_create_an_admin(self):
        password = "review-dummy-generated-password"
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "secrets.token_urlsafe", return_value=password
        ), patch("accounts.apps.os.open", side_effect=PermissionError("read-only")), redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, "Cannot securely store"):
                self._run_create_admin(tmp)
        self.assertNotIn(password, output.getvalue())
        self.assertFalse(get_user_model().objects.exists())

    def test_rerunning_migrate_after_a_storage_failure_creates_the_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("accounts.apps.os.open", side_effect=PermissionError("read-only")), redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    self._run_create_admin(tmp)
            # The second migrate has nothing left to apply: an empty plan.
            (Path(tmp) / "data").mkdir(exist_ok=True)
            self._run_create_admin(tmp, plan=[])
            self.assertTrue(get_user_model().objects.filter(username="admin").exists())

    def test_flush_does_not_create_an_admin(self):
        get_user_model().objects.all().delete()
        create_admin(sender=None, plan=None, apps=apps)
        self.assertFalse(get_user_model().objects.exists())

    def test_migrating_another_app_before_auth_creates_nothing(self):
        get_user_model().objects.all().delete()
        state_without_auth = MagicMock()
        state_without_auth.get_model.side_effect = LookupError
        create_admin(sender=None, plan=[], apps=state_without_auth)
        self.assertFalse(get_user_model().objects.exists())
