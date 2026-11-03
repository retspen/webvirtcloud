"""manage.py backup: a directory of what a new panel needs to take over,
readable only by the panel's user, the newest --keep of them kept."""

import fcntl
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from io import StringIO
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, override_settings

from appsettings.management.commands.backup import Command


SQLITE_ONLY = skipUnless(connection.vendor == "sqlite", "the backup copies only a sqlite database")


class BackupTests(SimpleTestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base)
        self.addCleanup(os.umask, os.umask(0o022))  # the command sets its own
        for path, text in (("data/secret_key", "key"), ("data/node_id", "a1b2c3"),
                           ("webvirtcloud/settings.py", "DEBUG = False"), ("home/.ssh/id_ed25519", "private")):
            (self.base / path).parent.mkdir(parents=True, exist_ok=True)
            (self.base / path).write_text(text)
        (self.base / "home/.ssh/agent").symlink_to(self.base / "data/secret_key")
        overridden = override_settings(BASE_DIR=self.base)
        overridden.enable()
        self.addCleanup(overridden.disable)
        home = patch.object(Path, "home", return_value=self.base / "home")
        home.start()
        self.addCleanup(home.stop)
        self.backups = self.base / "backups"

    def backup(self, *args):
        out = StringIO()
        call_command("backup", *args, stdout=out)
        return Path(out.getvalue().strip())

    def kept(self):
        return sorted(p.name for p in self.backups.iterdir() if p.name != ".lock")

    @SQLITE_ONLY
    def test_a_backup_holds_the_database_keys_and_settings_for_the_panel_user_only(self):
        backup = self.backup()
        with closing(sqlite3.connect(backup / "db.sqlite3")) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("computes_compute", tables)
        self.assertEqual(sorted(p.name for p in backup.iterdir()), ["db.sqlite3", "node_id", "secret_key", "settings.py", "ssh"])
        self.assertEqual((backup / "secret_key").read_text(), "key")
        self.assertEqual([p.name for p in (backup / "ssh").iterdir()], ["id_ed25519"])  # not what a link points to
        self.assertEqual(oct(self.backups.stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct(backup.stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct((backup / "db.sqlite3").stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct((backup / "ssh/id_ed25519").stat().st_mode & 0o777), "0o600")

    def test_only_the_newest_backups_and_no_partial_one_are_kept(self):
        for name in ("webvirtcloud-backup-20260101-000000", "webvirtcloud-backup-20260102-000000",
                     ".webvirtcloud-backup-20260103-000000"):
            (self.backups / name).mkdir(parents=True)
        backup = self.backup("--keep", "2")
        self.assertEqual(self.kept(), ["webvirtcloud-backup-20260102-000000", backup.name])

    def test_a_failed_backup_leaves_nothing_and_deletes_no_older_one(self):
        (self.backups / "webvirtcloud-backup-20260101-000000").mkdir(parents=True)
        with patch.object(Command, "copy", side_effect=OSError("No space left on device")), self.assertRaises(OSError):
            self.backup("--keep", "1")
        self.assertEqual(self.kept(), ["webvirtcloud-backup-20260101-000000"])

    @SQLITE_ONLY
    def test_a_damaged_copy_fails(self):
        with patch("appsettings.management.commands.backup.sqlite3") as sqlite, \
                self.assertRaisesRegex(CommandError, "damaged: row 3 missing from index"):
            sqlite.connect.return_value.execute.return_value.fetchone.return_value = ("row 3 missing from index",)
            self.backup()
        self.assertEqual(self.kept(), [])

    def test_a_backup_fails_while_another_runs(self):
        self.backups.mkdir()
        with open(self.backups / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(CommandError, "Another backup is running"):
                self.backup()
        self.assertEqual(self.kept(), [])

    def test_a_database_other_than_sqlite_is_left_out(self):
        errors = StringIO()
        with patch.dict(connection.settings_dict, ENGINE="django.db.backends.postgresql"):
            call_command("backup", stdout=StringIO(), stderr=errors)
        backup = self.backups / self.kept()[0]
        self.assertNotIn("db.sqlite3", [p.name for p in backup.iterdir()])
        self.assertIn("back it up with its own tools", errors.getvalue())
