"""Kinds used by the operations tests; registered on import. test.scripted
takes its behaviour from params and from barriers that tests install before
submitting (keyed by submission key). start_worker and stop_worker run a
worker's loop in a thread."""

import threading
from datetime import timedelta

from django.db import connection
from django.utils import timezone

from operations.jobs import Cancelled, Kind, Outcome, Plan, register
from operations.models import Claim, Operation, acquire

BARRIERS = {}  # submission key -> threading.Event the run waits on
CANCELLED = []
EXPIRED = []


def reset():
    BARRIERS.clear()
    CANCELLED.clear()
    EXPIRED.clear()


def start_worker(worker):
    """The loop of Worker.run in a thread, without its process parts."""
    acquire(worker.identity, worker.host)
    worker.recovery.schedule_orphans()

    def loop():
        try:
            while not worker.stopping.is_set():
                worker.tick_once()
                worker.stopping.wait(worker.tick)
        finally:
            connection.close()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def stop_worker(worker, thread):
    worker.stopping.set()
    thread.join(10)
    for pool in (worker.pool, worker.control, worker.progress_pool):
        pool.shutdown(wait=True, cancel_futures=True)


@register
class NoopKind(Kind):
    name = "test.noop"
    label = "No-op"

    def normalize(self, raw):
        return {"uuid": str(raw.get("uuid", "u1"))}

    def plan(self, user, params):
        key = "instance:" + params["uuid"]
        return Plan(claims={key: Claim.EXCLUSIVE}, resource=key, label="c/vm")

    def run(self, op, ctx):
        ctx.record_intent(step="effect")
        return {"done": True}

    def reconcile(self, op):
        return Outcome(Operation.SUCCEEDED, result={"recovered": True})

    def log_entry(self, op, state):
        return ("c", "vm", op.params["uuid"], f"No-op {state}")


@register
class ScriptedKind(NoopKind):
    """params: fail_before, fail_after, outcome (what reconcile returns)."""

    name = "test.scripted"
    label = "Scripted"
    cancellable = True

    def normalize(self, raw):
        return {"uuid": str(raw.get("uuid", "u1")), "fail_before": bool(raw.get("fail_before")),
                "fail_after": bool(raw.get("fail_after")), "outcome": str(raw.get("outcome", "uncertain"))}

    def run(self, op, ctx):
        if op.params["fail_before"]:
            raise RuntimeError("refused before effects")
        ctx.record_intent(step="effect")
        if op.params["fail_after"]:
            raise RuntimeError("failed after effects")
        barrier = BARRIERS.get(op.submission_key)
        if barrier is not None:
            barrier.wait(30)
            if str(op.id) in CANCELLED:
                raise Cancelled()
        return {"ran": True}

    def cancel(self, op):
        CANCELLED.append(str(op.id))
        barrier = BARRIERS.get(op.submission_key)
        if barrier is not None:
            barrier.set()

    def reconcile(self, op):
        return Outcome(op.params["outcome"], error="scripted")


@register
class RequestKind(NoopKind):
    """A job a request runs, idle after 60 s; params: fail_expire."""

    name = "test.request"
    label = "Request"
    cancellable = True
    runs_in_request = True

    def normalize(self, raw):
        return {"uuid": str(raw.get("uuid", "u1")), "fail_expire": bool(raw.get("fail_expire"))}

    def cancel(self, op):
        CANCELLED.append(str(op.id))

    def expire(self, op):
        if op.heartbeat_at > timezone.now() - timedelta(seconds=60):
            return
        if op.params["fail_expire"]:
            raise RuntimeError("expire failed")
        EXPIRED.append(str(op.id))
