import fcntl
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PREFIX = "webvirtcloud-backup-"


class Command(BaseCommand):
    help = ("Copy the database, secret key, worker id, settings and the SSH keys and TLS certificates of the "
            "panel's user into a new directory in backups/, then delete all but the newest --keep backups.")

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=7, help="how many backups to keep (default 7)")

    def handle(self, *args, keep, **options):
        if keep < 1:
            raise CommandError("--keep must be at least 1")
        os.umask(0o077)  # the database holds compute passwords and keys
        backups = settings.BASE_DIR / "backups"
        backups.mkdir(mode=0o700, exist_ok=True)
        with open(backups / ".lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CommandError("Another backup is running") from None
            self.stdout.write(str(self.backup(backups, keep)))

    def backup(self, backups, keep):
        name = PREFIX + datetime.now().strftime("%Y%m%d-%H%M%S")
        partial = backups / f".{name}"
        partial.mkdir()
        try:
            self.copy(partial)
            partial.rename(backups / name)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        # only after a good backup: a failing one never costs an older one;
        # the partial ones are what a killed run left behind
        for old in [*sorted(backups.glob(PREFIX + "*"))[:-keep], *backups.glob(f".{PREFIX}*")]:
            shutil.rmtree(old)
        return backups / name

    def copy(self, to):
        database = connection.settings_dict
        if database["ENGINE"] == "django.db.backends.sqlite3":
            # the backup API copies a consistent state while the panel writes
            read_only = Path(database["NAME"]).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(read_only, uri=True, timeout=30)) as source, \
                    closing(sqlite3.connect(to / "db.sqlite3")) as copy:
                source.backup(copy)
                result = copy.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise CommandError(f"The copy of the database is damaged: {result}")
        else:
            self.stderr.write("The database is not sqlite and is not in the backup: back it up with its own tools.")
        data = settings.BASE_DIR / "data"
        for source in (data / "secret_key", data / "node_id", settings.BASE_DIR / "webvirtcloud" / "settings.py"):
            if source.is_file():
                shutil.copyfile(source, to / source.name)
        ssh = Path.home() / ".ssh"
        if ssh.is_dir():
            (to / "ssh").mkdir()
            for source in ssh.iterdir():
                if source.is_file() and not source.is_symlink():
                    shutil.copyfile(source, to / "ssh" / source.name)
        # the TLS client certificates libvirt reads (~/.pki/libvirt); a link stays a link
        pki = Path.home() / ".pki"
        if pki.is_dir():
            shutil.copytree(pki, to / "pki", symlinks=True)
        if (settings.BASE_DIR / ".git").exists():
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=settings.BASE_DIR, capture_output=True, text=True)
            if commit.returncode == 0:
                (to / "commit").write_text(commit.stdout)
