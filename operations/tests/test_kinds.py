from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from operations import jobs
from operations.jobs import KINDS, Context, get_kind, label_of
from operations.models import TAKEOVER_AFTER, Claim, LeaseLost, Operation, WorkerLease, acquire, fenced, renew
from operations.tests import fakes


class RegistryTestCase(SimpleTestCase):
    def test_kinds_register_by_name(self):
        self.assertIs(get_kind("test.noop"), KINDS["test.noop"])
        self.assertEqual((label_of("test.noop"), label_of("unknown.kind")), ("No-op", "unknown.kind"))


class LeaseTestCase(TestCase):
    def test_the_first_worker_takes_the_lease_and_renews_it(self):
        self.assertTrue(acquire("h1:1:a", "h1"))
        self.assertTrue(renew("h1:1:a"))
        self.assertFalse(renew("h1:2:b"))

    def test_the_same_host_takes_over_at_once(self):
        acquire("h1:1:a", "h1")
        self.assertTrue(acquire("h1:2:b", "h1"))  # the caller holds the host's flock
        self.assertFalse(renew("h1:1:a"))

    def test_another_host_waits_until_the_lease_is_stale(self):
        acquire("h1:1:a", "h1")
        self.assertFalse(acquire("h2:1:c", "h2"))
        WorkerLease.objects.update(heartbeat_at=timezone.now() - TAKEOVER_AFTER - timedelta(seconds=1))
        self.assertTrue(acquire("h2:1:c", "h2"))

    def test_fenced_refuses_a_worker_without_the_lease(self):
        acquire("h1:1:a", "h1")
        with fenced("h1:1:a"):
            pass
        with self.assertRaises(LeaseLost):
            with fenced("h9:9:z"):
                pass


class ContextTestCase(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("ctx_user", "x@example.com", "pw")
        acquire("h1:1:a", "h1")
        self.worker = SimpleNamespace(identity="h1:1:a")
        self.op = Operation.objects.create(kind="test.noop", user=user, username="ctx_user", submission_key="k",
                                           resource="r", resource_label="r", state=Operation.RUNNING,
                                           worker="h1:1:a")

    def test_intent_is_committed_at_once(self):
        ctx = Context(self.op, self.worker)
        self.assertFalse(ctx.effects_started)
        ctx.record_intent(path="/pool/x.qcow2")
        self.op.refresh_from_db()
        self.assertTrue(ctx.effects_started and self.op.effects_started)
        self.assertEqual(self.op.intent, {"path": "/pool/x.qcow2"})

    def test_a_worker_without_the_lease_records_nothing(self):
        WorkerLease.objects.update(holder="h2:1:b", host="h2")
        ctx = Context(self.op, self.worker)
        with self.assertRaises(LeaseLost):
            ctx.record_intent(path="/pool/x.qcow2")
        self.op.refresh_from_db()
        self.assertEqual((self.op.intent, self.op.effects_started), ({}, False))
        self.assertFalse(ctx.effects_started)


class RequestJobTestCase(TestCase):
    def setUp(self):
        fakes.reset()
        self.user = get_user_model().objects.create_user("req_user", "q@example.com", "pw")

    def test_a_request_job_is_admitted_running_in_the_request(self):
        op = jobs.submit("test.request", self.user, {}, "key-00000001")
        op.refresh_from_db()
        self.assertEqual((op.state, op.worker, op.in_request), (Operation.RUNNING, Operation.REQUEST, True))
        self.assertIsNotNone(op.started_at)
        self.assertEqual(op.heartbeat_at, op.started_at)
        self.assertEqual(list(op.claims.values_list("resource", "mode")), [("instance:u1", Claim.EXCLUSIVE)])

    def test_the_same_submission_returns_the_running_request_job(self):
        op = jobs.submit("test.request", self.user, {}, "key-00000001")
        again = jobs.submit("test.request", self.user, {}, "key-00000001")
        self.assertEqual((again.pk, Operation.objects.count()), (op.pk, 1))

    def test_cancelling_a_request_job_runs_its_cancel_in_the_request(self):
        op = jobs.submit("test.request", self.user, {}, "key-00000001")
        op = jobs.cancel(op.pk, self.user)
        self.assertEqual((op.state, op.cancel_requested), (Operation.CANCELLING, True))
        self.assertEqual(fakes.CANCELLED, [str(op.pk)])
        jobs.cancel(op.pk, self.user)  # its stop did not end it: a repeated cancel retries
        self.assertEqual(fakes.CANCELLED, [str(op.pk)] * 2)

    def test_cancelling_a_workers_job_leaves_its_cancel_to_the_worker(self):
        op = jobs.submit("test.scripted", self.user, {}, "key-00000001")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="h1:1:a")
        op = jobs.cancel(op.pk, self.user)
        self.assertEqual(op.state, Operation.CANCELLING)
        jobs.cancel(op.pk, self.user)
        self.assertEqual(fakes.CANCELLED, [])
