"""A killed test run leaves its SQLite WAL files behind; the next run removes
them before it creates and clones the test database, or SQLite would replay
the old run's writes into the new one."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from webvirtcloud.test_runner import remove_wal_files


class RemoveWalFilesTests(SimpleTestCase):
    def test_the_wal_files_go_and_the_database_stays(self):
        with tempfile.TemporaryDirectory() as directory:
            name = Path(directory) / "test_db_1.sqlite3"
            for path in (name, Path(f"{name}-wal"), Path(f"{name}-shm")):
                path.write_bytes(b"x")
            remove_wal_files(name)
            remove_wal_files(name)  # none left: nothing to do
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["test_db_1.sqlite3"])
