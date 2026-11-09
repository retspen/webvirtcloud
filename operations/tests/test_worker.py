"""The worker runs queued jobs in its pool, sends errors before effects to
failed and after effects to inspection, honours cancel, and never records or
finishes after losing its lease."""

import os
import tempfile
import threading
import time
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from appsettings.models import AppSettings
from appsettings.settings import app_settings
from operations.utils import words
from operations import jobs
from operations.models import Claim, Operation, WorkerLease
from operations.tests import fakes
from operations.worker import Worker, _guarded, data_dir, host_identity, housekeeping, traceback_of
from vrtManager.util import ConnectionFailed


def wait_for(predicate, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def state(op):
    return Operation.objects.get(pk=op.pk).state


class WorkerTestCase(TransactionTestCase):
    def setUp(self):
        fakes.reset()
        self.user = get_user_model().objects.create_user("wk_user", "w@example.com", "pw")
        self.worker = None
        self.thread = None

    def start(self, concurrency=2):
        self.worker = Worker(concurrency=concurrency, tick=0.05, heartbeat_every=0.1, progress_every=0.1, grace=1,
                             exit_on_lost_lease=False)
        self.thread = fakes.start_worker(self.worker)

    def tearDown(self):
        for event in [*fakes.BARRIERS.values(), *fakes.STUCK.values()]:
            event.set()
        if self.thread:
            fakes.stop_worker(self.worker, self.thread)
        connection.close()

    def job(self, host, n):
        return self.submit("test.host", {"host": host, "n": n}, f"key-h{host}-{n:04d}")

    def test_a_stuck_housekeeping_pass_is_not_started_again(self):
        stuck, passes = threading.Event(), []

        def housekeeping():
            passes.append(1)
            stuck.wait(10)
        with patch("operations.worker.HOUSEKEEPING_EVERY", 0), patch("operations.worker.housekeeping", housekeeping):
            self.start()
            self.assertTrue(wait_for(lambda: passes))
            time.sleep(0.5)  # ten ticks
            self.assertEqual(len(passes), 1)
            stuck.set()
            self.assertTrue(wait_for(lambda: len(passes) > 1))

    def test_a_stuck_host_takes_half_the_slots_and_one_progress_read(self):
        fakes.STUCK[1] = threading.Event()
        stuck = [self.job(1, n) for n in range(4)]
        self.start(concurrency=4)
        self.assertTrue(wait_for(lambda: sum(state(op) == Operation.RUNNING for op in stuck) == 2))
        # the other host's job runs beside them, and its progress is read
        healthy = self.submit("test.host", {"host": 2, "n": 0}, "key-h2-0000", barrier=True)
        self.assertTrue(wait_for(lambda: ("progress", 2) in fakes.HOST_CALLS))
        self.assertEqual(sum(state(op) == Operation.RUNNING for op in stuck), 2)
        self.assertEqual(fakes.HOST_CALLS.count(("progress", 1)), 1)
        fakes.BARRIERS["key-h2-0000"].set()
        self.assertTrue(wait_for(lambda: state(healthy) == Operation.SUCCEEDED))

    def test_a_stuck_host_takes_one_control_thread(self):
        fakes.STUCK[1] = threading.Event()
        # they run until cancelled
        stuck = [self.submit("test.host", {"host": 1, "n": n}, f"key-h1-{n:04d}", barrier=True) for n in range(2)]
        healthy = self.submit("test.host", {"host": 2, "n": 0}, "key-h2-0000", barrier=True)
        self.start(concurrency=4)
        self.assertTrue(wait_for(lambda: all(state(op) == Operation.RUNNING for op in [*stuck, healthy])))
        for op in [*stuck, healthy]:
            jobs.cancel(op.pk, self.user)
        # the other host's cancel goes through; the stuck host's second cancel waits for its first
        # (the hooks start in no set order: wait for both)
        self.assertTrue(wait_for(lambda: ("cancel", 2) in fakes.HOST_CALLS and ("cancel", 1) in fakes.HOST_CALLS))
        self.assertEqual(fakes.HOST_CALLS.count(("cancel", 1)), 1)
        fakes.STUCK[1].set()
        self.assertTrue(wait_for(lambda: fakes.HOST_CALLS.count(("cancel", 1)) == 2))

    def submit(self, kind, params, key, barrier=False):
        if barrier:
            fakes.BARRIERS[key] = threading.Event()  # before the worker can see the job
        return jobs.submit(kind, self.user, params, key)

    def test_a_queued_job_runs_and_succeeds(self):
        op = self.submit("test.noop", {}, "key-00000001")
        self.start()
        self.assertTrue(wait_for(lambda: state(op) == Operation.SUCCEEDED))
        self.assertFalse(Claim.objects.exists())

    def test_a_job_sees_the_settings_page_values(self):
        # the worker has no settings middleware: it loads the values itself
        AppSettings.objects.create(name="t", key="TEST_WORKER_VALUE", value="42", choices="")
        if hasattr(app_settings, "TEST_WORKER_VALUE"):
            del app_settings.TEST_WORKER_VALUE
        op = self.submit("test.noop", {}, "key-00000009")
        with patch.object(fakes.NoopKind, "run", lambda kind, op, ctx: {"value": app_settings.TEST_WORKER_VALUE}):
            self.start()
            self.assertTrue(wait_for(lambda: state(op) in Operation.TERMINAL))
        op.refresh_from_db()
        self.assertEqual((op.state, op.result), (Operation.SUCCEEDED, {"value": "42"}), words(op.error))

    def test_an_error_before_effects_fails_the_job(self):
        op = self.submit("test.scripted", {"fail_before": True}, "key-00000001")
        self.start()
        self.assertTrue(wait_for(lambda: state(op) == Operation.FAILED))

    def test_a_connection_error_fails_the_job_without_naming_the_host(self):
        op = self.submit("test.noop", {}, "key-00000001")
        failure = ConnectionFailed("Cannot connect to qemu+ssh://root@wvc-test-host.example.com/system")
        with patch.object(fakes.NoopKind, "precheck", side_effect=failure):
            self.start()
            self.assertTrue(wait_for(lambda: state(op) == Operation.FAILED))
        error = words(Operation.objects.get(pk=op.pk).error)
        self.assertEqual(error, "The host of this virtual machine cannot be reached right now.")
        self.assertNotIn("example.com", error)

    def test_an_error_after_effects_goes_to_inspection(self):
        op = self.submit("test.scripted", {"fail_after": True, "outcome": "uncertain"}, "key-00000001")
        self.start()
        self.assertTrue(wait_for(lambda: state(op) == Operation.UNCERTAIN))
        self.assertTrue(Claim.objects.filter(operation=op).exists())

    def test_no_more_jobs_than_slots_run_at_once(self):
        ops = [self.submit("test.scripted", {"uuid": f"u{i}"}, f"key-0000000{i}", barrier=True) for i in range(3)]
        self.start()
        self.assertTrue(wait_for(lambda: Operation.objects.filter(state=Operation.RUNNING).count() == 2))
        time.sleep(0.3)
        self.assertEqual(Operation.objects.filter(state=Operation.QUEUED).count(), 1)
        for barrier in fakes.BARRIERS.values():
            barrier.set()
        self.assertTrue(wait_for(lambda: all(state(op) == Operation.SUCCEEDED for op in ops)))

    def test_a_cancelled_running_job_ends_cancelled(self):
        op = self.submit("test.scripted", {}, "key-00000001", barrier=True)
        self.start()
        self.assertTrue(wait_for(lambda: state(op) == Operation.RUNNING))
        jobs.cancel(op.pk, self.user)
        self.assertTrue(wait_for(lambda: state(op) == Operation.CANCELLED))
        self.assertFalse(Claim.objects.exists())

    def test_a_worker_that_lost_its_lease_does_not_finish_jobs(self):
        op = self.submit("test.scripted", {}, "key-00000001", barrier=True)
        self.start()
        self.assertTrue(wait_for(lambda: state(op) == Operation.RUNNING))
        WorkerLease.objects.update(holder="other-host:1:x", host="other-host")
        self.assertTrue(wait_for(lambda: self.worker.lost_lease))
        fakes.BARRIERS["key-00000001"].set()
        time.sleep(0.5)
        self.assertEqual(state(op), Operation.RUNNING)  # left for recovery

    def test_no_progress_is_written_after_the_lease_is_lost(self):
        release = threading.Event()

        def slow_progress(op):
            release.wait(5)
            return (1, 2)

        op = self.submit("test.scripted", {}, "key-00000001", barrier=True)
        fakes.ScriptedKind.progress = staticmethod(slow_progress)
        try:
            self.start()
            self.assertTrue(wait_for(lambda: state(op) == Operation.RUNNING))
            WorkerLease.objects.update(holder="other-host:1:x", host="other-host")
            release.set()
            self.assertTrue(wait_for(lambda: self.worker.lost_lease))
            time.sleep(0.3)
            self.assertIsNone(Operation.objects.get(pk=op.pk).progress_total)
        finally:
            release.set()
            del fakes.ScriptedKind.progress

    def test_heartbeats_continue_while_a_job_blocks(self):
        op = self.submit("test.scripted", {}, "key-00000001", barrier=True)
        self.start()
        self.assertTrue(wait_for(lambda: state(op) == Operation.RUNNING))
        first = Operation.objects.get(pk=op.pk).heartbeat_at
        self.assertTrue(wait_for(lambda: Operation.objects.get(pk=op.pk).heartbeat_at > first))

    def test_one_progress_query_per_job_at_a_time(self):
        calls, release = [], threading.Event()

        def slow_progress(op):
            calls.append(op.pk)
            release.wait(5)
            return (1, 2)

        self.submit("test.scripted", {}, "key-00000001", barrier=True)
        fakes.ScriptedKind.progress = staticmethod(slow_progress)
        try:
            self.start()
            self.assertTrue(wait_for(lambda: len(calls) == 1))
            time.sleep(0.5)  # several progress intervals while the query hangs
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            del fakes.ScriptedKind.progress

    def test_progress_queries_never_wait_for_a_thread(self):
        calls, release = [], threading.Event()

        def hanging_progress(op):
            calls.append(op.pk)
            release.wait(5)
            return (1, 2)

        for i in range(3):
            self.submit("test.scripted", {"uuid": f"u{i}"}, f"key-0000000{i}", barrier=True)
        fakes.ScriptedKind.progress = staticmethod(hanging_progress)
        try:
            self.start(concurrency=3)
            self.assertTrue(wait_for(lambda: len(calls) == 2))
            time.sleep(0.5)
            self.assertEqual(len(calls), 2)
            self.assertEqual(self.worker.progress_pool._work_queue.qsize(), 0)
        finally:
            release.set()
            del fakes.ScriptedKind.progress

    def test_progress_reaches_every_job_in_turn(self):
        ops = [self.submit("test.scripted", {"uuid": f"u{i}"}, f"key-0000000{i}", barrier=True) for i in range(3)]
        fakes.ScriptedKind.progress = staticmethod(lambda op: (1, 2))
        try:
            self.start(concurrency=3)
            self.assertTrue(wait_for(
                lambda: all(Operation.objects.get(pk=op.pk).progress_total == 2 for op in ops)))
        finally:
            del fakes.ScriptedKind.progress

    def test_a_cancel_during_the_drain_is_honoured(self):
        op = self.submit("test.scripted", {}, "key-00000001", barrier=True)
        self.start()
        self.assertTrue(wait_for(lambda: state(op) == Operation.RUNNING))
        self.worker.stopping.set()  # as SIGTERM: the loop ends, the drain begins
        self.thread.join(10)
        jobs.cancel(op.pk, self.user)
        self.worker._drain()
        self.assertEqual(state(op), Operation.CANCELLED)

    def test_a_job_thread_that_raised_before_its_effects_fails(self):
        op = self.submit("test.noop", {}, "key-00000001")
        with patch("operations.jobs.Context", side_effect=RuntimeError("no context")), \
                self.assertLogs("operations.worker", "WARNING") as logs:
            self.start()
            self.assertTrue(wait_for(lambda: state(op) == Operation.FAILED))
        # a fault of the panel: users read that, the log has the exception with its traceback
        self.assertEqual(words(Operation.objects.get(pk=op.pk).error), "The panel failed unexpectedly; its log has the details.")
        self.assertTrue(any("no context" in line and "Traceback" in line for line in logs.output))
        self.assertFalse(Claim.objects.filter(operation=op).exists())

    def test_a_traceback_in_the_log_has_no_secret(self):
        # as the message: the exception's text is written again at its end
        try:
            raise RuntimeError("password=review-dummy-secret")
        except RuntimeError as err:
            trace = traceback_of(err)
        self.assertIn("Traceback", trace)
        self.assertIn("password=***", trace)
        self.assertNotIn("review-dummy-secret", trace)

    def test_a_database_error_skips_a_tick(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.worker = Worker(data=directory.name, tick=0)
        errors = [OperationalError("database is locked"), OperationalError("server closed the connection")]

        def tick():
            if errors:
                raise errors.pop()
            self.worker.stopping.set()
        with (
            patch.object(self.worker, "tick_once", side_effect=tick),
            patch("operations.worker.signal.signal"),
            patch("operations.worker.logging.shutdown"),
            patch("operations.worker.os._exit", side_effect=SystemExit) as exit_,
            self.assertLogs("operations.worker", "ERROR"),
        ):
            with self.assertRaises(SystemExit):
                self.worker.run()
        exit_.assert_called_once_with(0)

    def test_a_failing_manager_loop_ends_the_process(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.worker = Worker(data=directory.name)
        with (
            patch.object(self.worker, "tick_once", side_effect=KeyError("a bug")),
            patch("operations.worker.signal.signal"),
            patch("operations.worker.logging.shutdown"),
            patch("operations.worker.os._exit", side_effect=SystemExit) as exit_,
        ):
            with self.assertRaises(SystemExit):
                self.worker.run()
        exit_.assert_called_once_with(1)


class RequestJobTestCase(TransactionTestCase):
    def setUp(self):
        fakes.reset()
        self.user = get_user_model().objects.create_user("rq_user", "q@example.com", "pw")

    def request_job(self, key, idle, **params):
        op = jobs.submit("test.request", self.user, params, key)
        Operation.objects.filter(pk=op.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=idle))
        return op

    def test_the_worker_never_takes_a_request_job(self):
        op = self.request_job("key-00000001", 0)
        worker = Worker(concurrency=2, tick=0.05, heartbeat_every=0.1, progress_every=0.1, grace=1,
                        exit_on_lost_lease=False)
        thread = fakes.start_worker(worker)
        try:
            time.sleep(0.5)
            self.assertEqual(worker.jobs, {})
        finally:
            fakes.stop_worker(worker, thread)
            connection.close()
        op.refresh_from_db()
        self.assertEqual((op.state, op.worker), (Operation.RUNNING, Operation.REQUEST))

    def test_housekeeping_lets_the_kind_expire_its_idle_request_jobs(self):
        fresh = self.request_job("key-00000001", 30, uuid="u1")
        idle = self.request_job("key-00000002", 61, uuid="u2")
        housekeeping()
        self.assertEqual(fakes.EXPIRED, [str(idle.pk)])
        self.assertNotIn(str(fresh.pk), fakes.EXPIRED)

    def test_housekeeping_removes_old_log_rows_and_expired_sessions(self):
        from django.contrib.sessions.models import Session
        from logs.models import Logs

        AppSettings.objects.update_or_create(key="LOG_RETENTION_DAYS", defaults={"name": "t", "value": "10", "choices": ""})
        old, kept = (Logs.objects.create(user="u", host="h", instance="vm", message=m) for m in ("old", "kept"))
        Logs.objects.filter(pk=old.pk).update(date=timezone.now() - timedelta(days=11))
        Logs.objects.filter(pk=kept.pk).update(date=timezone.now() - timedelta(days=9))
        Session.objects.create(session_key="expired-session", session_data="", expire_date=timezone.now() - timedelta(1))
        Session.objects.create(session_key="current-session", session_data="", expire_date=timezone.now() + timedelta(1))
        housekeeping()
        self.assertEqual(list(Logs.objects.values_list("message", flat=True)), ["kept"])
        self.assertEqual(list(Session.objects.values_list("session_key", flat=True)), ["current-session"])

    def test_one_failing_expire_does_not_stop_the_others(self):
        self.request_job("key-00000001", 61, uuid="u1", fail_expire=True)
        other = self.request_job("key-00000002", 61, uuid="u2")
        with self.assertLogs("operations.worker", "ERROR"):
            housekeeping()
        self.assertEqual(fakes.EXPIRED, [str(other.pk)])


class DataDirTestCase(SimpleTestCase):
    def test_the_data_dir_does_not_follow_the_log_file(self):
        with self.settings(WEBVIRTCLOUD_LOG_FILE="/var/log/wvc-test/webvirtcloud.log"):
            moved = data_dir()
        self.assertEqual(str(moved), str(settings.BASE_DIR / "data"))


class HostIdentityTestCase(SimpleTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = directory.name

    def test_the_same_data_dir_is_the_same_host(self):
        self.assertEqual(host_identity(self.dir), host_identity(self.dir))
        self.assertTrue(Worker(data=self.dir).identity.startswith(f"{host_identity(self.dir)}:"))

    def test_another_data_dir_is_another_host(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        self.assertNotEqual(host_identity(self.dir), host_identity(other.name))

    def test_an_id_another_worker_created_first_is_kept(self):
        def lose_the_race(src, dst):
            open(dst, "w").write("wvc-test-first")
            raise FileExistsError(dst)

        with patch("operations.worker.os.link", side_effect=lose_the_race):
            self.assertEqual(host_identity(self.dir), "wvc-test-first")
        self.assertEqual(sorted(os.listdir(self.dir)), ["node_id"])

    def test_a_new_hostname_on_the_same_data_dir_is_the_same_host(self):
        # a recreated container gets a new hostname but keeps its data volume
        with patch("operations.worker.socket.gethostname", return_value="wvc-test-a"):
            first = host_identity(self.dir)
        with patch("operations.worker.socket.gethostname", return_value="wvc-test-b"):
            self.assertEqual(host_identity(self.dir), first)



class CancelHookLogTests(SimpleTestCase):
    def test_a_failed_cancel_names_its_job(self):
        # every kind's hook is "cancel": the line alone said nothing of which job
        op = Operation(kind="instance.clone", resource_label="c1/vm-alpha", username="alice")

        def cancel(op):
            raise ConnectionFailed("Connection Failed: %(host)s did not answer within 5 s", host="192.0.2.10")
        with self.assertLogs("operations.worker", "ERROR") as logs:
            _guarded(cancel, op)
        self.assertEqual(logs.output, [f"ERROR:operations.worker:cancel of job {op.pk} (instance.clone, c1/vm-alpha, "
                                       "by alice) failed: Connection Failed: 192.0.2.10 did not answer within 5 s"])

    def test_housekeeping_runs_as_a_control_task_and_its_failure_is_logged(self):
        # the worker submits it without a job
        ran = []
        _guarded(lambda: ran.append(True))
        self.assertEqual(ran, [True])

        def housekeeping():
            raise RuntimeError("disk full")
        with self.assertLogs("operations.worker", "ERROR") as logs:
            _guarded(housekeeping)
        self.assertTrue(logs.output[0].startswith("ERROR:operations.worker:housekeeping failed: disk full\nTraceback"))
