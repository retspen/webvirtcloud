"""Resources held by jobs and by short requests (spec section 2). A request
or a job writes its claims in one short transaction, only if no active
claim conflicts; otherwise it is refused at once (Busy)."""

import os
import socket
import threading
from contextlib import contextmanager
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from .models import Claim

# gunicorn ends a request after its timeout (gunicorn.conf.py: 600 s); a
# short operation's claim is certainly orphaned after that.
TRANSIENT_TTL = timedelta(seconds=600 + 60)


class Busy(Exception):
    """A resource is held. blocker: the job holding it, None for a short operation."""

    def __init__(self, resource, blocker=None):
        super().__init__(f"{resource} is busy")
        self.resource = resource
        self.blocker = blocker


def compute_key(compute_id):
    return f"compute:{compute_id}"


def reconcile_key(compute_id):
    return f"reconcile:{compute_id}"


def instance_key(uuid):
    return f"instance:{uuid}"


def pool_key(compute_id, pool):
    return f"pool:{compute_id}:{pool}"


def volume_key(compute_id, pool, name):
    return f"volume:{compute_id}:{pool}/{name}"


def name_key(name):
    """A VM name is the panel's on every compute (the name checks are global)."""
    return f"name:{name}"


def quota_key(user_id):
    return f"quota:user:{user_id}"


def holder_id():
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


def serialize(keys):
    """Inside a transaction: admissions touching one of these keys run one at
    a time. SQLite: the IMMEDIATE transaction already holds the write lock."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            for key in sorted(set(keys)):
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def _check(wanted, now):
    Claim.objects.filter(operation__isnull=True, expires_at__lte=now, resource__in=list(wanted)).delete()
    active = (
        Claim.objects.filter(resource__in=list(wanted))
        .filter(Q(operation__isnull=False) | Q(expires_at__gt=now))
        .select_related("operation")
        .order_by("resource")
    )
    for claim in active:
        if wanted[claim.resource] == Claim.EXCLUSIVE or claim.mode == Claim.EXCLUSIVE:
            raise Busy(claim.resource, claim.operation)


def admit(wanted, *, holder, ttl=None):
    """Transient claims for a short operation; Busy if anything conflicts."""
    with transaction.atomic():
        serialize(wanted)
        now = timezone.now()
        _check(wanted, now)
        rows = [Claim(resource=k, mode=m, holder=holder, expires_at=now + (ttl or TRANSIENT_TTL))
                for k, m in sorted(wanted.items())]
        return [c.pk for c in Claim.objects.bulk_create(rows)]


def admit_job(op, wanted, existing, extra_locks=()):
    """Save the unsaved job op with its claims. existing() runs first, under
    the same locks (extra_locks: e.g. the submission key), and its job is
    returned unchanged when it finds one."""
    with transaction.atomic():
        serialize([*wanted, *extra_locks])
        now = timezone.now()
        found = existing()
        if found is not None:
            return found
        _check(wanted, now)
        op.save()
        Claim.objects.bulk_create([Claim(operation=op, resource=k, mode=m) for k, m in sorted(wanted.items())])
        return op


_local = threading.local()


def _held():
    if not hasattr(_local, "held"):
        _local.held = {}
    return _local.held


@contextmanager
def hold(wanted):
    """Transient claims for the block. Keys this thread holds are reused;
    exclusive covers shared; shared cannot become exclusive inside its block."""
    held = _held()
    new = {}
    for key, mode in wanted.items():
        if key in held:
            if held[key] == Claim.SHARED and mode == Claim.EXCLUSIVE:
                raise RuntimeError(f"Cannot upgrade a shared claim on {key}")
            continue
        new[key] = mode
    if not new:
        yield
        return
    ids = admit(new, holder=holder_id())
    held.update(new)
    try:
        yield
    finally:
        for key in new:
            held.pop(key, None)
        Claim.objects.filter(pk__in=ids).delete()


@contextmanager
def adopted(op):
    """The job thread holds its job's claims, so code it calls that takes a
    lock helper does not refuse its own job."""
    held = _held()
    own = dict(Claim.objects.filter(operation=op).values_list("resource", "mode"))
    held.update(own)
    try:
        yield
    finally:
        for key in own:
            held.pop(key, None)
