"""The job worker (spec section 3). The manager loop never calls libvirt: job
threads run kinds; control threads run cancel hooks and recovery; progress
threads read progress. Every write is fenced by the lease. Recovery of
interrupted jobs (spec section 4): inspection decides from intent and libvirt;
nothing is re-run; uncertain keeps its claims."""

import fcntl
import logging
import os
import signal
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from django.utils.translation import gettext_noop

from appsettings.settings import get_settings

from . import claims, jobs, utils
from .models import Claim, LeaseLost, Operation, acquire, fenced, renew

logger = logging.getLogger(__name__)

MAX_SLOTS = 16
PROGRESS_THREADS = 2
HOUSEKEEPING_EVERY = 600.0

BACKOFF = (30, 60, 120, 300, 600)
WATCH_EVERY = 15
STALL_LIMIT = 600  # a block job left at cur == end after a libvirtd restart never ends
STALLED = gettext_noop("libvirt's merge finished copying but never completed (for example after a "
                       "libvirtd restart); check the VM before resolving")
ABANDONED = gettext_noop("The worker that ran this job stopped responding; an administrator must make sure it "
                         "is no longer running, then resolve this job")
WAITING = gettext_noop("Waiting for recovery")
ACTIVE = (Operation.RUNNING, Operation.CANCELLING)


def data_dir():
    """The installation's persistent data directory (the Docker volume)."""
    data = settings.BASE_DIR / "data"
    os.makedirs(data, exist_ok=True)
    return data


def host_identity(data):
    """The worker's host: a random id created once in the data directory,
    which also holds the worker's flock. A recreated container on the same
    volume is the same host (the flock proves its old worker is gone);
    another installation sharing the database is another host, even with
    the same hostname. The hostname is not part of it: Docker gives a
    recreated container a new one."""
    path = Path(data) / "node_id"
    if not path.exists():
        new = path.with_name(f"node_id.{uuid.uuid4().hex}")  # PIDs repeat across containers
        new.write_text(uuid.uuid4().hex[:12])
        try:
            os.link(new, path)  # never replaces an id another process just created
        except FileExistsError:
            pass
        finally:
            new.unlink()
    return path.read_text().strip()


class Worker:
    def __init__(self, concurrency=None, tick=1.0, heartbeat_every=10.0, progress_every=5.0, grace=60.0,
                 data=None, exit_on_lost_lease=True):
        data = Path(data or data_dir())
        self.host = host_identity(data)
        self.identity = f"{self.host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.fixed_concurrency = concurrency
        self.tick = tick
        self.heartbeat_every = heartbeat_every
        self.progress_every = progress_every
        self.grace = grace
        self.lock_path = data / "worker.lock"
        self.exit_on_lost_lease = exit_on_lost_lease
        self.stopping = threading.Event()
        self.lost_lease = False
        self.jobs = {}
        self.signalled = set()
        self.progress_pending = set()
        self.progress_asked = {}  # job -> monotonic time its progress was last asked
        self.pool = ThreadPoolExecutor(MAX_SLOTS, thread_name_prefix="wvc-job")
        self.control = ThreadPoolExecutor(4, thread_name_prefix="wvc-control")
        self.progress_pool = ThreadPoolExecutor(PROGRESS_THREADS, thread_name_prefix="wvc-progress")
        self.recovery = Scheduler(self)
        self._last = {"heartbeat": 0.0, "progress": 0.0, "housekeeping": 0.0}

    # -- process ------------------------------------------------------------

    def run(self):
        """Until SIGTERM. Returns 1 if another worker runs on this host. Ends
        with os._exit, so job threads past the grace period end with it; a
        failing manager loop ends the process the same way (status 1)."""
        lock = open(self.lock_path, "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("Another worker runs on this host; exiting")
            return 1
        signal.signal(signal.SIGTERM, lambda *_: self.stopping.set())
        signal.signal(signal.SIGINT, lambda *_: self.stopping.set())
        status = 0
        try:
            while not acquire(self.identity, self.host):
                if self.stopping.wait(5):
                    return 0
            logger.info("Worker %s started on %s", self.identity, socket.gethostname())
            self.recovery.schedule_orphans()
            while not self.stopping.is_set():
                self.tick_once()
                self.stopping.wait(self.tick)
            self._drain()
        except Exception as err:
            logger.error("Worker %s failed: %s", self.identity, utils.safe_text(err))
            status = 1
        logger.info("Worker %s stopped", self.identity)
        logging.shutdown()
        os._exit(status)

    def _drain(self):
        end = time.monotonic() + self.grace
        while self.jobs and time.monotonic() < end:
            if not self._renew():
                return
            self._heartbeat()
            self._reap()
            self._cancels()
            time.sleep(min(self.tick, 1.0))

    def _lose_lease(self):
        logger.error("Worker %s lost its lease", self.identity)
        self.lost_lease = True
        self.stopping.set()
        if self.exit_on_lost_lease:
            logging.shutdown()
            os._exit(1)  # self-fencing: no job thread of ours reaches libvirt again

    def _renew(self):
        if not renew(self.identity):
            self._lose_lease()
            return False
        return True

    # -- loop ---------------------------------------------------------------

    def tick_once(self):
        now = time.monotonic()
        if now - self._last["heartbeat"] >= self.heartbeat_every:
            self._last["heartbeat"] = now
            if not self._renew():
                return
            self._heartbeat()
        self._reap()
        self._cancels()
        self._limits()
        if now - self._last["progress"] >= self.progress_every:
            self._last["progress"] = now
            self._progress()
        self.recovery.due()
        self._claim()
        if now - self._last["housekeeping"] >= HOUSEKEEPING_EVERY:
            self._last["housekeeping"] = now
            self.control.submit(_guarded, housekeeping)

    def _mine(self, pks):
        """This worker's active jobs among pks; used only inside fenced."""
        return Operation.objects.filter(pk__in=list(pks), worker=self.identity, state__in=Operation.ACTIVE)

    def _fenced_update(self, pks, **fields):
        try:
            with fenced(self.identity):
                return self._mine(pks).update(**fields)
        except LeaseLost:
            self._lose_lease()
            return 0

    def _heartbeat(self):
        if self.jobs:
            self._fenced_update(self.jobs, heartbeat_at=timezone.now())

    def _reap(self):
        for op_id, future in list(self.jobs.items()):
            if future.done():
                del self.jobs[op_id]
                self.signalled.discard(op_id)
                self.progress_asked.pop(op_id, None)
                if (err := future.exception()) is not None:
                    # execute raised before it could finish the job itself
                    logger.error("job %s ended unfinished: %s", op_id, utils.safe_text(err))
                    self.control.submit(_guarded, self.recovery.inspect_now, op_id, utils.public_error(err))

    def _slots(self):
        return (self.fixed_concurrency or utils.concurrency()) - len(self.jobs)

    def _claim(self):
        while self._slots() > 0 and not self.stopping.is_set():
            candidate = (Operation.objects.filter(state=Operation.QUEUED).order_by("created_at")
                         .values_list("pk", flat=True).first())
            if candidate is None:
                return
            try:
                with fenced(self.identity):
                    now = timezone.now()
                    taken = Operation.objects.filter(pk=candidate, state=Operation.QUEUED).update(
                        state=Operation.RUNNING, started_at=now, heartbeat_at=now, worker=self.identity)
            except LeaseLost:
                self._lose_lease()
                return
            if taken:
                self.jobs[candidate] = self.pool.submit(execute, self, candidate)

    def _cancels(self):
        for op in Operation.objects.filter(pk__in=list(self.jobs), cancel_requested=True):
            if op.pk not in self.signalled:
                self.signalled.add(op.pk)
                self.control.submit(_guarded, jobs.get_kind(op.kind).cancel, op)

    def _limits(self):
        now = timezone.now()
        for op in Operation.objects.filter(pk__in=list(self.jobs), time_limit__isnull=False):
            if op.started_at and now - op.started_at > timedelta(seconds=op.time_limit):
                # one that cannot be cancelled runs on; its page says it is over its limit
                if jobs.get_kind(op.kind).cancellable and not op.cancel_requested:
                    self._fenced_update([op.pk], state=Operation.CANCELLING, cancel_requested=True)

    def _progress(self):
        """At most one query per job and none waiting for a thread, so queries
        that hang in libvirt do not pile up; the least recently asked first."""
        ops = Operation.objects.filter(pk__in=list(self.jobs))
        for op in sorted(ops, key=lambda op: self.progress_asked.get(op.pk, 0.0)):
            if len(self.progress_pending) >= PROGRESS_THREADS:
                return
            if op.pk not in self.progress_pending:
                self.progress_pending.add(op.pk)
                self.progress_asked[op.pk] = time.monotonic()
                self.progress_pool.submit(self._read_progress, op)

    def _read_progress(self, op):
        try:
            value = jobs.get_kind(op.kind).progress(op)
            if value is not None:
                with fenced(self.identity):
                    self._mine([op.pk]).update(progress_done=value[0], progress_total=value[1])
        except Exception as err:
            logger.debug("progress of job %s: %s", op.pk, utils.safe_text(err))
        finally:
            self.progress_pending.discard(op.pk)
            close_old_connections()


def _guarded(fn, *args):
    try:
        fn(*args)
    except Exception as err:
        logger.error("worker task %s failed: %s", getattr(fn, "__name__", fn), utils.safe_text(err))
    finally:
        close_old_connections()


def execute(worker, op_id):
    """A job thread: precheck and run. Errors before effects fail the job;
    after effects they go to inspection; a lost lease leaves it alone."""
    op = Operation.objects.get(pk=op_id)
    kind = jobs.get_kind(op.kind)
    ctx = jobs.Context(op, worker)
    get_settings()  # the Settings page values; only requests load them otherwise (middleware)
    try:
        with claims.adopted(op):
            kind.precheck(op, ctx)
            result = kind.run(op, ctx)
        jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED, result=result), worker=worker)
    except LeaseLost:
        logger.warning("job %s left for recovery: this worker lost its lease", op_id)
    except jobs.Cancelled:
        jobs.finish(op, jobs.Outcome(Operation.CANCELLED), worker=worker)
    except Exception as err:
        logger.warning("job %s %s raised: %s", op.pk, op.kind, utils.safe_text(err))
        try:
            # jobs have no request: the error users see never names a host
            if ctx.effects_started:
                worker.recovery.inspect_now(op.pk, error=utils.public_error(err))
            else:
                jobs.finish(op, jobs.Outcome(Operation.FAILED, error=utils.public_error(err)), worker=worker)
        except LeaseLost:
            pass
    finally:
        close_old_connections()


def housekeeping():
    cutoff = timezone.now() - timedelta(days=utils.retention_days())
    old = list(
        Operation.objects.filter(state__in=Operation.TERMINAL, finished_at__lt=cutoff)
        .exclude(state=Operation.UNCERTAIN).exclude(claims__isnull=False)
        .values_list("pk", flat=True)[:500]
    )
    Operation.objects.filter(pk__in=old).delete()
    Claim.objects.filter(operation__isnull=True, expires_at__lt=timezone.now()).delete()
    # each kind ends its idle jobs; HOUSEKEEPING_EVERY bounds how late an idle request job ends
    for op in Operation.objects.filter(state__in=ACTIVE, worker=Operation.REQUEST):
        try:
            jobs.get_kind(op.kind).expire(op)
        except Exception as err:
            logger.error("expiring job %s failed: %s", op.pk, utils.safe_text(err))


class Scheduler:
    def __init__(self, worker):
        self.worker = worker
        self.next_try = {}
        self.attempts = {}
        self.errors = {}
        self.stalled_since = {}
        self.inflight = set()

    def schedule_orphans(self):
        """Other workers' active jobs; not those requests run."""
        for op_id in (Operation.objects.filter(state__in=ACTIVE)
                      .exclude(worker__in=[self.worker.identity, Operation.REQUEST])
                      .values_list("pk", flat=True)):
            self.next_try.setdefault(op_id, 0)

    def inspect_now(self, op_id, error=()):
        self.errors[op_id] = error
        self.next_try[op_id] = 0

    def due(self):
        now = time.monotonic()
        for op_id, at in list(self.next_try.items()):
            if at <= now and op_id not in self.inflight:
                self.inflight.add(op_id)
                self.worker.control.submit(self._inspect, op_id)

    def _done(self, op_id):
        for table in (self.next_try, self.attempts, self.errors, self.stalled_since):
            table.pop(op_id, None)

    def _take_over(self, op):
        """True if op is now this worker's. Another host's job ends uncertain
        in the same transaction, so a failed finish leaves its owner as it was."""
        previous = op.worker
        previous_host = previous.split(":", 1)[0]
        with fenced(self.worker.identity):
            if not (Operation.objects.filter(pk=op.pk, worker=previous, state__in=ACTIVE)
                    .update(worker=self.worker.identity)):
                self._done(op.pk)
                return False
            op.refresh_from_db()
            if previous_host != self.worker.host:
                # the error is shown to the job's owner: the host goes to the worker log only
                self._finish(op, jobs.Outcome(Operation.UNCERTAIN, error=utils.say(ABANDONED)))
                logger.warning("job %s ended uncertain: its worker %s stopped responding", op.pk, previous)
                return False
        return True

    def _finish(self, op, outcome):
        jobs.finish(op, outcome, worker=self.worker)
        self._done(op.pk)

    def _error(self, op_id, finding):
        """What an unproven end stores: the error the job raised, then what libvirt shows."""
        return [*self.errors.get(op_id, ()), *finding]

    def _phase(self, op_id, text, progress=None):
        fields = {"phase": utils.safe_text(text)[:255]} if text else {}
        if progress is not None:
            fields.update(progress_done=progress[0], progress_total=progress[1])
        if not fields:
            return
        with fenced(self.worker.identity):
            Operation.objects.filter(pk=op_id, worker=self.worker.identity, state__in=ACTIVE).update(**fields)

    def _inspect(self, op_id):
        try:
            op = Operation.objects.get(pk=op_id)
            if op.state not in ACTIVE:
                self._done(op_id)
                return
            if op.worker != self.worker.identity and not self._take_over(op):
                return
            if not op.effects_started:
                self._finish(op, jobs.Outcome(Operation.FAILED, error=list(self.errors.get(op_id, ()))
                                         or utils.say(gettext_noop("The worker stopped before the job changed anything"))))
                return
            try:
                outcome = jobs.get_kind(op.kind).reconcile(op)
            except Exception as err:
                n = self.attempts.get(op_id, 0)
                self.attempts[op_id] = n + 1
                self.next_try[op_id] = time.monotonic() + BACKOFF[min(n, len(BACKOFF) - 1)]
                self._phase(op_id, WAITING)
                logger.warning("recovery of job %s waits: %s", op_id, utils.safe_text(err))
                return
            if outcome.state == Operation.RUNNING:
                now = time.monotonic()
                if not outcome.stalled:
                    self.stalled_since.pop(op_id, None)
                elif now - self.stalled_since.setdefault(op_id, now) >= STALL_LIMIT:
                    self._finish(op, jobs.Outcome(Operation.UNCERTAIN, error=self._error(op_id, utils.say(STALLED))))
                    return
                self.next_try[op_id] = now + WATCH_EVERY
                self._phase(op_id, outcome.phase, outcome.progress)
                return
            # the error the job raised does not describe a proven success
            error = outcome.error if outcome.state == Operation.SUCCEEDED else self._error(op_id, outcome.error)
            self._finish(op, jobs.Outcome(outcome.state, outcome.result, error, outcome.phase))
        except LeaseLost:
            self._done(op_id)
        except Exception as err:
            logger.error("recovery of job %s failed: %s", op_id, utils.safe_text(err))
            self.next_try[op_id] = time.monotonic() + BACKOFF[-1]
        finally:
            self.inflight.discard(op_id)
            close_old_connections()
