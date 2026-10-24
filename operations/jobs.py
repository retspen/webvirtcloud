"""The contract every kind of job follows (spec section 5), the kinds by name
(filled by each app's jobs.py via register) and the context a running job
reports through. Submitting, cancelling, finishing and resolving jobs (spec
sections 2-5)."""

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from logs.audit import write
from vrtManager.util import OperationError

from . import claims, utils
from .models import Claim, LeaseLost, Operation, fenced

logger = logging.getLogger(__name__)

KINDS = {}

SUBMISSION_KEY_TTL = timedelta(hours=24)
KEY_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


@dataclass
class Plan:
    claims: dict
    resource: str
    label: str
    intent: dict = field(default_factory=dict)


@dataclass
class Outcome:
    """What a run or an inspection decided. RUNNING: libvirt still works;
    stalled: its work reports nothing left to do but does not end;
    progress: (done, total) of that work, when libvirt tells."""

    state: str
    result: dict = field(default_factory=dict)
    error: str = ""
    phase: str = ""
    stalled: bool = False
    progress: tuple | None = None


class Cancelled(Exception):
    """Raised by a kind's run when a cancel stopped its work."""


def get_kind(name):
    return KINDS[name]


def label_of(name):
    kind = KINDS.get(name)
    return kind.label if kind is not None else name


def register(cls):
    KINDS[cls.name] = cls()
    return cls


class Kind:
    name = ""
    label = ""
    cancellable = False
    time_limit = None
    runs_in_request = False  # its requests run it: admitted running, never the worker's
    progress_bytes = False  # progress counts bytes: the job page shows sizes

    def normalize(self, raw):
        """Plain, allowlisted values from the request, without libvirt."""
        raise NotImplementedError

    def validate(self, user, params):
        """In the request: permissions and libvirt state. Raise to refuse."""

    def plan(self, user, params):
        raise NotImplementedError

    def precheck(self, op, ctx):
        """In the worker, before any effect: permission and state again."""

    def run(self, op, ctx):
        raise NotImplementedError

    def progress(self, op):
        return None

    def cancel(self, op):
        raise NotImplementedError

    def reconcile(self, op):
        raise NotImplementedError

    def expire(self, op):
        """Called on every housekeeping pass for an active job a request runs;
        the kind decides whether the job is idle and ends it if so."""

    def log_entry(self, op, state):
        """(host, instance, instance UUID, message) of the Logs row written
        with each end of the job (in the same transaction); its host, instance
        and UUID also go on the row of a resolution. None: no row."""
        return None


class Context:
    def __init__(self, op, worker):
        self.op = op
        self.worker = worker
        self.effects_started = False

    def _write(self, **fields):
        with fenced(self.worker.identity):
            if not Operation.objects.filter(pk=self.op.pk, worker=self.worker.identity).update(**fields):
                raise LeaseLost("the job is no longer this worker's")
        for name, value in fields.items():
            setattr(self.op, name, value)

    def record_intent(self, **values):
        """Commit what run is about to change; the first libvirt effect may
        follow only after this returns."""
        self._write(intent={**self.op.intent, **values}, effects_started=True)
        self.effects_started = True

    def set_phase(self, text):
        self._write(phase=utils.safe_text(text)[:255])


class SubmissionConflict(Exception):
    """A submission key reused for another request."""


def _existing(user, key, kind_name, params):
    op = Operation.objects.filter(user=user, submission_key=key).first()
    if op is None:
        return None
    if op.created_at < timezone.now() - SUBMISSION_KEY_TTL:
        Operation.objects.filter(pk=op.pk).update(submission_key=f"expired:{op.pk.hex}")
        return None
    if op.kind != kind_name or op.params != params:
        raise SubmissionConflict("This form was already submitted for another request; reload the page")
    return op


def submit(kind_name, user, raw_params, submission_key):
    if not KEY_RE.fullmatch(submission_key or ""):
        raise OperationError("The form has no valid submission key; reload the page")
    kind = get_kind(kind_name)
    params = kind.normalize(raw_params)
    utils.check_params(params)
    if (op := _existing(user, submission_key, kind.name, params)) is not None:
        return op
    lock = f"submission:{user.pk}:{submission_key}"
    try:
        kind.validate(user, params)
        plan = kind.plan(user, params)
    except Exception:
        # a concurrent duplicate may have been admitted (and even run) meanwhile
        with transaction.atomic():
            claims.serialize([lock])
            if (op := _existing(user, submission_key, kind.name, params)) is not None:
                return op
        raise
    op = Operation(
        kind=kind.name, user=user, username=user.username, submission_key=submission_key,
        resource=plan.resource, resource_label=plan.label[:255], params=params, intent=plan.intent,
        time_limit=kind.time_limit,
    )
    if kind.runs_in_request:
        now = timezone.now()
        op.state, op.started_at, op.heartbeat_at, op.worker = Operation.RUNNING, now, now, Operation.REQUEST
    return claims.admit_job(
        op, plan.claims,
        existing=lambda: _existing(user, submission_key, kind.name, params),
        extra_locks=[lock],
    )


def cancel(op_id, user):
    with transaction.atomic():
        op = Operation.objects.select_for_update().get(pk=op_id)
        if not utils.may_see(op, user):
            raise PermissionDenied
        # read before the update below; a repeated cancel retries the request job's stop
        request_job = op.in_request and op.state in (Operation.RUNNING, Operation.CANCELLING)
        if op.state == Operation.QUEUED:
            Operation.objects.filter(pk=op.pk).update(state=Operation.CANCELLED, finished_at=timezone.now())
            Claim.objects.filter(operation=op).delete()
            if (entry := _entry(op, Operation.CANCELLED)) is not None:
                _log(op.username, *entry, None)
        elif op.state == Operation.RUNNING:
            if not get_kind(op.kind).cancellable:
                raise OperationError("This job cannot be cancelled once it has started")
            Operation.objects.filter(pk=op.pk).update(state=Operation.CANCELLING, cancel_requested=True)
        elif op.state != Operation.CANCELLING:
            raise OperationError("The job has already ended")
    op.refresh_from_db()
    if request_job:  # no worker signals it: the request stops it
        get_kind(op.kind).cancel(op)
        op.refresh_from_db()
    return op


def _entry(op, state):
    """The kind's log entry; one that cannot be computed is logged and skipped, so it never undoes the job."""
    try:
        return get_kind(op.kind).log_entry(op, state)
    except Exception:
        logging.getLogger("logs.audit").exception("log entry of job %s not computed", op.pk)
        return None


def _log(user, host, instance, uuid, message, success):
    write(str(user), str(host), str(instance), utils.safe_text(message), success, uuid=str(uuid))


def finish(op, outcome, *, worker=None):
    """Terminal state, claims and history together, once. With a worker,
    only while it holds the lease and owns the job. Uncertain keeps the claims."""
    error = utils.safe_text(outcome.error)
    with fenced(worker.identity) if worker is not None else transaction.atomic():
        q = Operation.objects.filter(pk=op.pk, state__in=Operation.ACTIVE)
        if worker is not None:
            q = q.filter(worker=worker.identity)
        # success clears the phase and completes the progress; another end keeps the last ones
        done = outcome.state == Operation.SUCCEEDED
        if not q.update(state=outcome.state, result=outcome.result, error=error,
                        phase=Value(outcome.phase[:255]) if outcome.phase else ("" if done else F("phase")),
                        progress_done=Coalesce(F("progress_total"), F("progress_done")) if done else F("progress_done"),
                        finished_at=timezone.now()):
            return False
        if outcome.state != Operation.UNCERTAIN:
            Claim.objects.filter(operation=op).delete()
        if (entry := _entry(op, outcome.state)) is not None:
            _log(op.username, *entry, {Operation.SUCCEEDED: True, Operation.FAILED: False}.get(outcome.state))
    logger.info("job %s %s: %s", op.pk, op.kind, outcome.state)
    op.refresh_from_db()
    return True


def resolve(op_id, user, outcome_state, note):
    if not user.is_superuser:
        raise PermissionDenied
    if outcome_state not in (Operation.SUCCEEDED, Operation.FAILED):
        raise OperationError("Choose succeeded or failed")
    note = note.strip()
    if not note:
        raise OperationError("Write a note on what was checked")
    with transaction.atomic():
        op = Operation.objects.select_for_update().get(pk=op_id)
        if op.state != Operation.UNCERTAIN:
            raise OperationError("Only an uncertain job can be resolved")
        Operation.objects.filter(pk=op.pk).update(state=outcome_state, resolution=outcome_state,
                                                  resolution_note=note, resolved_by=user, resolved_at=timezone.now())
        Claim.objects.filter(operation=op).delete()
        # the host, VM and UUID columns of the kind's own entries, so the VM's log shows it
        entry = _entry(op, outcome_state)
        host, instance, uuid = entry[:3] if entry is not None else ("-", op.resource_label, "")
        _log(user.username, host, instance, uuid, f"Job {op.pk} resolved as {outcome_state}: {note}",
             outcome_state == Operation.SUCCEEDED)
    op.refresh_from_db()
    return op


def remember_job(request, op):
    """The resource page's panel shows this job even if it ends before the first poll."""
    entries = request.session.get("operations_shown", [])
    request.session["operations_shown"] = [*entries, {"resource": op.resource, "id": str(op.pk)}][-20:]


def take_remembered(request, resource):
    """The ids remembered for resource; the other resources' entries stay."""
    entries = request.session.get("operations_shown", [])
    taken = [e["id"] for e in entries if e["resource"] == resource]
    if taken:  # untouched otherwise: no session write on every page view
        request.session["operations_shown"] = [e for e in entries if e["resource"] != resource]
    return taken
