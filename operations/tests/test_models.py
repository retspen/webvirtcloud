"""The job record: states, defaults, the per-user submission key, and the
SQLite connection mode every process relies on."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from operations.models import Claim, Operation


def new_op(user, key="k", **kw):
    return Operation.objects.create(kind="test.noop", user=user, username=user.username, submission_key=key,
                                    resource="instance:u1", resource_label="c/vm", **kw)


class OperationModelTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("jobs_user", "j@example.com", "pw")

    def test_a_new_operation_is_queued_with_empty_records(self):
        op = new_op(self.user)
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.QUEUED)
        self.assertEqual((op.params, op.intent, op.result), ({}, {}, {}))
        self.assertIn(Operation.QUEUED, Operation.ACTIVE)
        self.assertIn(Operation.UNCERTAIN, Operation.TERMINAL)

    def test_a_submission_key_is_unique_per_user(self):
        new_op(self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            new_op(self.user)

    def test_claims_go_with_their_operation(self):
        op = new_op(self.user)
        Claim.objects.create(operation=op, resource="instance:u1", mode=Claim.EXCLUSIVE)
        op.delete()
        self.assertFalse(Claim.objects.exists())


class SqliteModeTestCase(TestCase):
    def test_sqlite_runs_in_wal_with_immediate_transactions(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite only")
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            self.assertEqual(cursor.fetchone()[0].lower(), "wal")
        self.assertEqual(connection.transaction_mode, "IMMEDIATE")
