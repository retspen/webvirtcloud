"""manage.py test --parallel on the SQLite database in WAL mode."""

import multiprocessing

from django.test.runner import DiscoverRunner, ParallelTestSuite


def _init_worker(*args, **kwargs):
    # Pool processes are daemonic, and a daemonic process may have no
    # children; the operations process tests start workers of their own.
    multiprocessing.current_process().daemon = False
    ParallelTestSuite.init_worker(*args, **kwargs)


class _ParallelTestSuite(ParallelTestSuite):
    init_worker = _init_worker


class TestRunner(DiscoverRunner):
    parallel_test_suite = _ParallelTestSuite

    def setup_databases(self, **kwargs):
        # Django clones a SQLite test database by copying its main file, but
        # migrate's writes are still in the WAL file (operations/apps.py):
        # create the database alone, write the WAL back, then clone.
        parallel, self.parallel = self.parallel, 0
        old_config = super().setup_databases(**kwargs)
        self.parallel = parallel
        for connection, _, created in old_config:
            if not created or parallel < 2:
                continue
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            for index in range(parallel):
                connection.creation.clone_test_db(
                    suffix=str(index + 1), verbosity=self.verbosity, keepdb=self.keepdb
                )
        return old_config
