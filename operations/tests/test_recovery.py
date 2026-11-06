from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from operations.utils import say, words
from operations import jobs
from operations.jobs import Outcome
from operations.models import Claim, Operation, WorkerLease, acquire
from operations.tests import fakes
from operations.worker import ABANDONED, RECOVERY_LIMIT, STALL_LIMIT, STALLED, UNREACHABLE, WAITING, Scheduler


class FakeWorker:
    host = "this-host"
    identity = "this-host:2:new"
    lost_lease = False

    def __init__(self):
        self.control = ThreadPoolExecutor(1)

    def run_control(self, hosts, fn, *args):
        self.control.submit(fn, *args)
        return True


class RecoveryTestCase(TransactionTestCase):
    def setUp(self):
        fakes.reset()
        self.user = get_user_model().objects.create_user("rec_user", "r@example.com", "pw")
        self.worker = FakeWorker()
        acquire(self.worker.identity, self.worker.host)
        self.scheduler = Scheduler(self.worker)

    def tearDown(self):
        self.worker.control.shutdown(wait=True)

    def orphan(self, params, worker="this-host:1:old", effects=True):
        op = jobs.submit("test.scripted", self.user, params, "key-00000001")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=worker,
                                                  intent={"step": "effect"}, effects_started=effects)
        return op

    def run_due(self):
        self.scheduler.schedule_orphans()
        self.scheduler.due()
        self.worker.control.shutdown(wait=True)
        self.worker.control = ThreadPoolExecutor(1)

    def reload(self, op):
        op.refresh_from_db()
        return op

    def test_a_proven_success_is_released(self):
        op = self.orphan({"outcome": "succeeded"})
        self.run_due()
        self.assertEqual(self.reload(op).state, Operation.SUCCEEDED)
        self.assertFalse(Claim.objects.exists())

    def test_a_proven_success_does_not_carry_the_raised_error(self):
        op = self.orphan({}, worker=self.worker.identity)
        self.scheduler.inspect_now(op.pk, error=say("failed after effects"))
        with patch.object(fakes.ScriptedKind, "reconcile", return_value=Outcome(Operation.SUCCEEDED)):
            self.run_due()
        op = self.reload(op)
        self.assertEqual((op.state, words(op.error)), (Operation.SUCCEEDED, ""))

    def test_an_uncertain_outcome_keeps_the_error_the_job_raised(self):
        op = self.orphan({}, worker=self.worker.identity)
        self.scheduler.inspect_now(op.pk, error=say("resource busy: X"))
        with patch.object(fakes.ScriptedKind, "reconcile",
                          return_value=Outcome(Operation.UNCERTAIN, error=say("check the VM"))):
            self.run_due()
        op = self.reload(op)
        self.assertEqual((op.state, words(op.error)), (Operation.UNCERTAIN, "resource busy: X. check the VM"))

    def test_uncertain_keeps_the_claims(self):
        op = self.orphan({"outcome": "uncertain"})
        self.run_due()
        self.assertEqual(self.reload(op).state, Operation.UNCERTAIN)
        self.assertTrue(Claim.objects.filter(operation=op).exists())

    def test_still_running_in_libvirt_keeps_watching(self):
        op = self.orphan({"outcome": "running"})
        self.run_due()
        op = self.reload(op)
        self.assertEqual((op.state, op.worker), (Operation.RUNNING, self.worker.identity))
        self.assertIn(op.pk, self.scheduler.next_try)

    def run_at(self, now, outcome):
        with patch("operations.worker.time.monotonic", return_value=now), \
                patch.object(fakes.ScriptedKind, "reconcile", return_value=outcome):
            self.run_due()

    def test_watching_stores_the_progress_libvirt_reports(self):
        op = self.orphan({})
        self.run_at(1000, Outcome(Operation.RUNNING, phase="merging", progress=(3, 8)))
        op = self.reload(op)
        self.assertEqual((op.phase, op.progress_done, op.progress_total), ("merging", 3, 8))
        self.scheduler.next_try[op.pk] = 0
        self.run_at(1015, Outcome(Operation.RUNNING, progress=(5, 8)))
        op = self.reload(op)
        self.assertEqual((op.phase, op.progress_done, op.progress_total), ("merging", 5, 8))

    def test_watching_writes_no_progress_without_the_lease(self):
        op = self.orphan({}, worker=self.worker.identity)
        WorkerLease.objects.update(holder="other-host:9:z")
        self.run_at(1000, Outcome(Operation.RUNNING, progress=(3, 8)))
        self.assertIsNone(self.reload(op).progress_done)

    def test_a_stalled_merge_is_watched_until_the_stall_limit(self):
        op = self.orphan({})
        self.run_at(1000, Outcome(Operation.RUNNING, stalled=True))
        self.run_at(1000 + STALL_LIMIT - 1, Outcome(Operation.RUNNING, stalled=True))
        self.assertEqual(self.reload(op).state, Operation.RUNNING)
        self.assertIn(op.pk, self.scheduler.next_try)

    def test_a_merge_stalled_past_the_limit_ends_uncertain_and_keeps_the_claims(self):
        op = self.orphan({})
        self.run_at(1000, Outcome(Operation.RUNNING, stalled=True))
        self.run_at(1000 + STALL_LIMIT, Outcome(Operation.RUNNING, stalled=True))
        op = self.reload(op)
        self.assertEqual((op.state, words(op.error)), (Operation.UNCERTAIN, STALLED))
        self.assertTrue(Claim.objects.filter(operation=op).exists())
        self.assertNotIn(op.pk, self.scheduler.stalled_since)

    def test_a_stalled_merge_keeps_the_error_the_job_raised(self):
        op = self.orphan({}, worker=self.worker.identity)
        self.scheduler.inspect_now(op.pk, error=say("resource busy: X"))
        self.run_at(1000, Outcome(Operation.RUNNING, stalled=True))
        self.scheduler.next_try[op.pk] = 0
        self.run_at(1000 + STALL_LIMIT, Outcome(Operation.RUNNING, stalled=True))
        self.assertEqual(words(self.reload(op).error), f"resource busy: X. {STALLED}")

    def test_a_raised_error_ending_with_a_dot_is_not_doubled(self):
        op = self.orphan({}, worker=self.worker.identity)
        self.scheduler.inspect_now(op.pk, error=say("refused."))
        with patch.object(fakes.ScriptedKind, "reconcile", return_value=Outcome(Operation.UNCERTAIN, error=say("check"))):
            self.run_due()
        self.assertEqual(words(self.reload(op).error), "refused. check")

    def test_an_outcome_without_an_error_stores_the_raised_one(self):
        op = self.orphan({}, worker=self.worker.identity)
        self.scheduler.inspect_now(op.pk, error=say("resource busy: X"))
        with patch.object(fakes.ScriptedKind, "reconcile", return_value=Outcome(Operation.FAILED)):
            self.run_due()
        self.assertEqual(words(self.reload(op).error), "resource busy: X")

    def test_progress_resets_the_stall_timer(self):
        op = self.orphan({})
        self.run_at(1000, Outcome(Operation.RUNNING, stalled=True))
        self.run_at(1300, Outcome(Operation.RUNNING))
        self.run_at(1400, Outcome(Operation.RUNNING, stalled=True))
        self.run_at(1000 + STALL_LIMIT + 100, Outcome(Operation.RUNNING, stalled=True))
        self.assertEqual(self.reload(op).state, Operation.RUNNING)

    def test_an_unreachable_host_waits_with_growing_intervals(self):
        op = self.orphan({})
        with patch.object(fakes.ScriptedKind, "reconcile", side_effect=OSError("host down")):
            self.run_due()
        op = self.reload(op)
        self.assertEqual((op.state, op.phase), (Operation.RUNNING, WAITING))
        self.assertEqual(self.scheduler.attempts[op.pk], 1)

    def test_a_host_unreachable_for_the_recovery_limit_ends_the_job_uncertain(self):
        op = self.orphan({})
        for now in (1000, 1000 + RECOVERY_LIMIT - 1, 1000 + RECOVERY_LIMIT):
            self.scheduler.next_try[op.pk] = 0
            with patch("operations.worker.time.monotonic", return_value=now), \
                    patch.object(fakes.ScriptedKind, "reconcile", side_effect=OSError("host down")):
                self.run_due()
            self.assertEqual(self.reload(op).state,
                             Operation.UNCERTAIN if now == 1000 + RECOVERY_LIMIT else Operation.RUNNING)
        self.assertTrue(words(op.error).endswith(UNREACHABLE))
        self.assertTrue(Claim.objects.filter(operation=op).exists())

    def test_an_answer_restarts_the_recovery_limit(self):
        op = self.orphan({})
        with patch("operations.worker.time.monotonic", return_value=1000), \
                patch.object(fakes.ScriptedKind, "reconcile", side_effect=OSError("host down")):
            self.run_due()
        self.scheduler.next_try[op.pk] = 0
        self.run_at(1100, Outcome(Operation.RUNNING))
        self.assertNotIn(op.pk, self.scheduler.failing_since)

    def test_a_cancel_of_a_job_libvirt_still_runs_goes_to_libvirt_once(self):
        op = self.orphan({})
        Operation.objects.filter(pk=op.pk).update(state=Operation.CANCELLING, cancel_requested=True)
        with patch.object(fakes.ScriptedKind, "cancel") as cancel:
            self.run_at(1000, Outcome(Operation.RUNNING))
            self.scheduler.next_try[op.pk] = 0
            self.run_at(1015, Outcome(Operation.RUNNING))
        cancel.assert_called_once()
        self.assertEqual(cancel.call_args.args[0].pk, op.pk)

    def test_a_job_without_a_cancel_is_watched_without_one(self):
        self.orphan({})
        with patch.object(fakes.ScriptedKind, "cancel") as cancel:
            self.run_at(1000, Outcome(Operation.RUNNING))
        cancel.assert_not_called()

    def test_a_job_that_never_recorded_its_intent_fails(self):
        op = self.orphan({}, effects=False)
        self.run_due()
        self.assertEqual(self.reload(op).state, Operation.FAILED)

    def test_another_hosts_orphan_ends_uncertain_without_inspection(self):
        op = self.orphan({"outcome": "succeeded"}, worker="other-host:1:old")
        with patch.object(fakes.ScriptedKind, "reconcile") as reconcile, \
                self.assertLogs("operations.worker", "WARNING") as logs:
            self.run_due()
        reconcile.assert_not_called()
        op = self.reload(op)
        # the stored error is shown to the job's owner: the host goes to the worker log only
        self.assertEqual((op.state, words(op.error)), (Operation.UNCERTAIN, ABANDONED))
        self.assertNotIn("other-host", words(op.error))
        self.assertIn("other-host", "\n".join(logs.output))
        self.assertTrue(Claim.objects.filter(operation=op).exists())

    def test_another_hosts_orphan_stays_theirs_if_it_cannot_end_uncertain(self):
        op = self.orphan({"outcome": "succeeded"}, worker="other-host:1:old")
        with patch.object(jobs, "finish", side_effect=RuntimeError("database is down")):
            self.run_due()
        op = self.reload(op)
        self.assertEqual((op.state, op.worker), (Operation.RUNNING, "other-host:1:old"))

    def test_this_workers_own_jobs_are_not_orphans(self):
        op = self.orphan({"outcome": "succeeded"}, worker=self.worker.identity)
        self.run_due()
        self.assertEqual(self.reload(op).state, Operation.RUNNING)

    def test_a_request_job_is_not_an_orphan(self):
        op = jobs.submit("test.request", self.user, {}, "key-00000002")
        self.run_due()
        self.assertEqual(self.scheduler.next_try, {})
        self.assertEqual(self.reload(op).state, Operation.RUNNING)

    def test_an_own_job_that_raised_before_its_effects_fails_and_releases(self):
        op = self.orphan({"outcome": "uncertain"}, worker=self.worker.identity, effects=False)
        self.scheduler.inspect_now(op.pk, error=say("refused before effects"))
        self.run_due()
        op = self.reload(op)
        self.assertEqual(op.state, Operation.FAILED)
        self.assertFalse(Claim.objects.exists())
