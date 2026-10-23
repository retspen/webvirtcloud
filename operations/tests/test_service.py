from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone
from vrtManager.util import OperationError

from logs.models import Logs
from operations import claims, jobs
from operations.jobs import Outcome
from operations.models import Claim, LeaseLost, Operation, WorkerLease, acquire
from operations.tests import fakes

KEY = "key-00000001"


class SubmitTestCase(TransactionTestCase):
    def setUp(self):
        fakes.reset()
        self.user = get_user_model().objects.create_user("svc_user", "s@example.com", "pw")

    def test_a_job_is_queued_with_its_claims(self):
        op = jobs.submit("test.noop", self.user, {"uuid": "u1"}, KEY)
        self.assertEqual(op.state, Operation.QUEUED)
        self.assertEqual(list(op.claims.values_list("resource", "mode")), [("instance:u1", Claim.EXCLUSIVE)])

    def test_the_same_submission_returns_the_same_job_without_validating_again(self):
        first = jobs.submit("test.noop", self.user, {"uuid": "u1"}, KEY)
        with patch.object(fakes.NoopKind, "validate") as validate:
            again = jobs.submit("test.noop", self.user, {"uuid": "u1"}, KEY)
        self.assertEqual(first.pk, again.pk)
        validate.assert_not_called()

    def test_a_reused_key_with_other_inputs_or_kind_is_refused(self):
        jobs.submit("test.noop", self.user, {"uuid": "u1"}, KEY)
        with self.assertRaises(jobs.SubmissionConflict):
            jobs.submit("test.noop", self.user, {"uuid": "u2"}, KEY)
        with self.assertRaises(jobs.SubmissionConflict):
            jobs.submit("test.scripted", self.user, {"uuid": "u1"}, KEY)

    def test_a_bad_key_is_refused(self):
        with self.assertRaises(OperationError):
            jobs.submit("test.noop", self.user, {}, "x")

    def test_secret_params_are_refused(self):
        with patch("operations.utils.check_params", side_effect=ValueError("secret")), self.assertRaises(ValueError):
            jobs.submit("test.noop", self.user, {}, KEY)
        self.assertFalse(Operation.objects.exists())

    def test_a_duplicate_whose_validation_fails_returns_the_job_admitted_meanwhile(self):
        first = jobs.submit("test.noop", self.user, {"uuid": "u1"}, KEY)
        real = jobs._existing
        calls = []

        def unseen_first(*args):
            calls.append(args)
            return None if len(calls) == 1 else real(*args)  # the duplicate looked before the first was admitted

        with patch.object(jobs, "_existing", side_effect=unseen_first), \
                patch.object(fakes.NoopKind, "validate", side_effect=OperationError("gone")):
            again = jobs.submit("test.noop", self.user, {"uuid": "u1"}, KEY)
        self.assertEqual(again.pk, first.pk)

    def test_a_conflicting_job_is_refused_and_nothing_is_saved(self):
        jobs.submit("test.noop", self.user, {"uuid": "u1"}, KEY)
        with self.assertRaises(claims.Busy):
            jobs.submit("test.noop", self.user, {"uuid": "u1"}, "key-00000002")
        self.assertEqual(Operation.objects.count(), 1)

    def test_an_expired_key_starts_a_new_job(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        jobs.finish(op, Outcome(Operation.SUCCEEDED))
        Operation.objects.filter(pk=op.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.assertNotEqual(jobs.submit("test.noop", self.user, {}, KEY).pk, op.pk)


class CancelFinishResolveTestCase(TransactionTestCase):
    def setUp(self):
        fakes.reset()
        U = get_user_model()
        self.user = U.objects.create_user("svc2", "s2@example.com", "pw")
        self.admin = U.objects.create_superuser("svc_admin", "a@example.com", "pw")

    def test_a_queued_job_is_cancelled_at_once_releases_its_claims_and_is_logged(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        self.assertEqual(jobs.cancel(op.pk, self.user).state, Operation.CANCELLED)
        self.assertFalse(Claim.objects.exists())
        self.assertEqual(list(Logs.objects.values_list("message", flat=True)), ["No-op cancelled"])

    def test_a_failing_log_entry_does_not_undo_the_finish(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        with patch.object(fakes.NoopKind, "log_entry", side_effect=RuntimeError("x")), \
                self.assertLogs("logs.audit", "ERROR"):
            self.assertTrue(jobs.finish(op, Outcome(Operation.SUCCEEDED)))
        self.assertEqual(Operation.objects.get(pk=op.pk).state, Operation.SUCCEEDED)
        self.assertFalse(Claim.objects.exists())
        self.assertFalse(Logs.objects.exists())

    def test_job_rows_carry_the_result(self):
        for key, state, success in (("key-00000002", Operation.SUCCEEDED, True), ("key-00000003", Operation.FAILED, False)):
            jobs.finish(jobs.submit("test.noop", self.user, {}, key), Outcome(state))
            self.assertIs(Logs.objects.latest("pk").success, success)
        jobs.cancel(jobs.submit("test.noop", self.user, {}, "key-00000004").pk, self.user)
        self.assertIsNone(Logs.objects.latest("pk").success)
        op = jobs.submit("test.noop", self.user, {}, "key-00000005")
        jobs.finish(op, Outcome(Operation.UNCERTAIN))
        self.assertIsNone(Logs.objects.latest("pk").success)
        jobs.resolve(op.pk, self.admin, Operation.FAILED, "checked")
        self.assertIs(Logs.objects.latest("pk").success, False)

    def test_cancel_decides_from_the_current_state(self):
        op = jobs.submit("test.scripted", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING)  # the worker took it meanwhile
        self.assertEqual(jobs.cancel(op.pk, self.user).state, Operation.CANCELLING)
        self.assertTrue(Operation.objects.get(pk=op.pk).cancel_requested)

    def test_only_the_owner_or_a_superuser_cancels(self):
        other = get_user_model().objects.create_user("svc3", "s3@example.com", "pw")
        op = jobs.submit("test.noop", self.user, {}, KEY)
        with self.assertRaises(PermissionDenied):
            jobs.cancel(op.pk, other)
        jobs.cancel(op.pk, self.admin)

    def test_a_running_job_of_a_kind_that_cannot_stop_is_not_cancelled(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING)
        with self.assertRaisesRegex(OperationError, "cannot be cancelled"):
            jobs.cancel(op.pk, self.user)

    def test_success_clears_the_phase_and_completes_the_progress(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(phase="merging", progress_done=6424625152, progress_total=6442450944)
        jobs.finish(op, Outcome(Operation.SUCCEEDED))
        op.refresh_from_db()
        self.assertEqual((op.phase, op.progress_done, op.progress_total), ("", 6442450944, 6442450944))

    def test_success_without_a_total_leaves_the_progress_unset(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        jobs.finish(op, Outcome(Operation.SUCCEEDED))
        op.refresh_from_db()
        self.assertEqual((op.progress_done, op.progress_total), (None, None))

    def test_success_keeps_the_progress_when_there_is_no_total(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(progress_done=5)
        jobs.finish(op, Outcome(Operation.SUCCEEDED))
        op.refresh_from_db()
        self.assertEqual((op.progress_done, op.progress_total), (5, None))

    def test_a_failure_keeps_the_phase_stored_after_the_job_was_loaded(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(phase="merging")  # op in memory still has ""
        jobs.finish(op, Outcome(Operation.FAILED, error="x"))
        op.refresh_from_db()
        self.assertEqual(op.phase, "merging")

    def test_a_failure_keeps_the_last_phase_and_progress(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(phase="merging", progress_done=5, progress_total=10)
        op.refresh_from_db()
        jobs.finish(op, Outcome(Operation.FAILED, error="x"))
        op.refresh_from_db()
        self.assertEqual((op.phase, op.progress_done), ("merging", 5))

    def test_finish_happens_once(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        self.assertTrue(jobs.finish(op, Outcome(Operation.SUCCEEDED, result={"x": 1})))
        self.assertFalse(jobs.finish(op, Outcome(Operation.FAILED, error="late")))
        op.refresh_from_db()
        self.assertEqual((op.state, op.result), (Operation.SUCCEEDED, {"x": 1}))
        self.assertEqual(Logs.objects.count(), 1)
        self.assertFalse(Claim.objects.exists())

    def test_finish_by_a_worker_without_the_lease_changes_nothing(self):
        acquire("h1:1:a", "h1")
        op = jobs.submit("test.noop", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="h1:1:a")
        WorkerLease.objects.update(holder="h2:1:b", host="h2")
        with self.assertRaises(LeaseLost):
            jobs.finish(op, Outcome(Operation.SUCCEEDED), worker=SimpleNamespace(identity="h1:1:a"))
        self.assertEqual(Operation.objects.get(pk=op.pk).state, Operation.RUNNING)

    def test_errors_and_logs_carry_no_secrets_and_fit_the_columns(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        Operation.objects.filter(pk=op.pk).update(username="u" * 150)
        op.refresh_from_db()
        jobs.finish(op, Outcome(Operation.FAILED, error="qemu+tcp://admin:s3cret@192.0.2.5/system failed"))
        op.refresh_from_db()
        self.assertNotIn("s3cret", op.error)
        self.assertLessEqual(len(Logs.objects.get().user), 150)

    def test_an_uncertain_job_keeps_its_claims_until_resolved(self):
        op = jobs.submit("test.noop", self.user, {}, KEY)
        jobs.finish(op, Outcome(Operation.UNCERTAIN, error="check the disks"))
        self.assertTrue(Claim.objects.filter(operation=op).exists())
        with self.assertRaises(PermissionDenied):
            jobs.resolve(op.pk, self.user, Operation.FAILED, "checked")
        with self.assertRaisesRegex(OperationError, "note"):
            jobs.resolve(op.pk, self.admin, Operation.FAILED, "  ")
        jobs.resolve(op.pk, self.admin, Operation.FAILED, "disks checked, nothing changed")
        op.refresh_from_db()
        self.assertEqual((op.state, op.resolution, op.resolved_by_id), (Operation.FAILED, Operation.FAILED, self.admin.pk))
        self.assertFalse(Claim.objects.exists())
        entry = Logs.objects.get(message__icontains="resolved")
        self.assertEqual((entry.user, entry.host, entry.instance), (self.admin.username, "c", "vm"))


class RememberJobTestCase(SimpleTestCase):
    def test_the_last_twenty_jobs_are_remembered_until_taken(self):
        request = SimpleNamespace(session={})
        for n in range(25):
            jobs.remember_job(request, SimpleNamespace(pk=n, resource="instance:a"))
        self.assertEqual(len(request.session["operations_shown"]), 20)
        self.assertEqual(jobs.take_remembered(request, "instance:a"), [str(n) for n in range(5, 25)])
        self.assertEqual(jobs.take_remembered(request, "instance:a"), [])

    def test_a_resource_takes_only_its_own_jobs(self):
        request = SimpleNamespace(session={})
        jobs.remember_job(request, SimpleNamespace(pk=1, resource="instance:a"))
        jobs.remember_job(request, SimpleNamespace(pk=2, resource="instance:b"))
        self.assertEqual(jobs.take_remembered(request, "instance:a"), ["1"])
        self.assertEqual(request.session["operations_shown"], [{"resource": "instance:b", "id": "2"}])
        self.assertEqual(jobs.take_remembered(request, "instance:b"), ["2"])
