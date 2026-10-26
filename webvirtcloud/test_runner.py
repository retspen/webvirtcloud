"""manage.py test --parallel on the SQLite database in WAL mode."""

import contextlib
import os

from django.db import connections
from django.test.runner import DiscoverRunner


def remove_wal_files(name):
    """Django replaces a SQLite test database by its main file only. A run
    that was killed or whose pool crashed leaves the database's WAL behind,
    and SQLite would replay that run's writes into the new database."""
    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.remove(f"{name}{suffix}")


class TestRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        if not isinstance(suite, self.parallel_test_suite):
            return suite
        # Pool workers are daemonic and may start no processes: the test
        # cases tagged "processes" run in this process after the pool.
        serial = [case for case in suite.subsuites if "processes" in getattr(next(iter(case)), "tags", ())]
        suite.subsuites = [case for case in suite.subsuites if case not in serial]
        return self.test_suite([suite, *serial])

    def setup_databases(self, **kwargs):
        # Django clones a SQLite test database by copying its main file, but
        # migrate's writes are still in the WAL file (operations/apps.py):
        # create the database alone, write the WAL back, then clone.
        parallel, self.parallel = self.parallel, 0
        test_files = [c.settings_dict["TEST"]["NAME"] for c in connections.all() if c.vendor == "sqlite"]
        for name in filter(None, test_files) if not self.keepdb else ():
            remove_wal_files(name)
        old_config = super().setup_databases(**kwargs)
        self.parallel = parallel
        for connection, _, created in old_config:
            if not created or parallel < 2:
                continue
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    if cursor.fetchone()[0]:
                        raise RuntimeError("The test database's WAL could not be written back before cloning")
            for index in range(parallel):
                if connection.vendor == "sqlite" and not self.keepdb:
                    remove_wal_files(connection.creation.get_test_db_clone_settings(str(index + 1))["NAME"])
                connection.creation.clone_test_db(
                    suffix=str(index + 1), verbosity=self.verbosity, keepdb=self.keepdb
                )
        return old_config
