"""Backup schedules, run by the worker about once a minute (its periodic
tasks): each schedule's VMs backed up once a local day within WINDOW of its
time, each VM's backups of the schedule beyond keep deleted, and each target
checked once a day. The jobs run as the schedule's owner."""

import datetime
import logging
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.translation import gettext_noop as _
from libvirt import libvirtError

from computes.models import Compute
from operations import claims, jobs
from operations.models import Operation
from operations.utils import safe_text, said, say
from vrtManager.util import ConnectionFailed

from .jobs import beyond_keep
from .models import Backup, BackupPolicy, BackupRun, BackupTarget

logger = logging.getLogger(__name__)

WINDOW = datetime.timedelta(hours=6)  # a run is admitted this long after its time, else skipped
NOT_STARTED = _("Not started within 6 hours of its time")
IN_MAINTENANCE = _("The host was in maintenance")
NO_OWNER = _("The schedule's owner is no longer an active superuser")
RETRY_AFTER = datetime.timedelta(hours=1)  # a deletion or check that failed is tried again after this

# each compute's submissions in a task of their own, at most one a compute: with a thread for every
# compute, hung hosts take no thread a healthy host's task needs (threads start only when needed)
THREADS = 64
_pool = ThreadPoolExecutor(THREADS, thread_name_prefix="wvc-schedule")
_tasks = {}  # compute id -> the future of its last task


def run_schedules(now=None):
    now = now or timezone.now()
    due = {}  # compute id -> [(policy, vm, day)]
    for policy in BackupPolicy.objects.filter(enabled=True).select_related("owner"):
        for day, start in occurrences(policy, now):
            open_ = now < start + WINDOW
            done = set(BackupRun.objects.filter(policy=policy, day=day).values_list("instance_id", flat=True))
            for vm in policy.vms():
                if vm.pk in done:
                    continue
                in_maintenance = Compute.objects.filter(pk=vm.compute_id, maintenance_since__isnull=False).exists()
                if not open_:
                    _record(policy, vm, day, BackupRun.SKIPPED, say(IN_MAINTENANCE if in_maintenance else NOT_STARTED))
                elif not in_maintenance:  # deferred while the window lasts
                    due.setdefault(vm.compute_id, []).append((policy.pk, vm.pk, day, start))
    for compute_id, items in due.items():
        task = _tasks.get(compute_id)
        if task is None or task.done():
            _tasks[compute_id] = _pool.submit(_submit_all, compute_id, items)
    retain()
    check_targets(now)


def occurrences(policy, now):
    """(local day, instant) of the schedule's times yesterday and today that
    have come and are not older than the schedule: a late time's window goes
    on after midnight. A time a spring-forward gap skips falls an hour later
    (zoneinfo, fold 0); a time repeated in autumn is its first."""
    zone = timezone.get_default_timezone()
    today = timezone.localtime(now, zone).date()
    for day in (today - datetime.timedelta(days=1), today):
        # in UTC: the window is real hours, also on a day the clocks change
        start = datetime.datetime.combine(day, policy.time, tzinfo=zone).astimezone(datetime.timezone.utc)
        if policy.created_at <= start <= now:
            yield day, start


def _record(policy, vm, day, state, note=(), operation=None):
    BackupRun.objects.get_or_create(policy=policy, instance=vm, day=day,
                                    defaults={"state": state, "note": list(note), "operation": operation})


def _active_superuser(user):
    return user is not None and user.is_active and user.is_superuser


def _submit_all(compute_id, items):
    """One compute's due backups, one after another, each checked again as
    it comes: the task may have waited for a thread. A busy target or an
    unreachable host is tried again at the next pass."""
    try:
        for policy_id, vm_id, day, start in items:
            _submit(policy_id, vm_id, day, start)
    finally:
        close_old_connections()  # a thread of the pool: its connection is its own


def _submit(policy_id, vm_id, day, start):
    policy = BackupPolicy.objects.select_related("owner").filter(pk=policy_id, enabled=True).first()
    now = timezone.now()
    if policy is None or now >= start + WINDOW or (day, start) not in set(occurrences(policy, now)):
        return  # disabled, deleted or its time moved meanwhile, or its window ended: the next pass decides
    vm = policy.vms().filter(pk=vm_id).first()
    if vm is None or BackupRun.objects.filter(policy=policy, instance=vm, day=day).exists():
        return
    if Compute.objects.filter(pk=vm.compute_id, maintenance_since__isnull=False).exists():
        return
    if not _active_superuser(policy.owner):
        _record(policy, vm, day, BackupRun.FAILED, say(NO_OWNER))
        return
    # the same key for the same run: a worker stopped before the row was written gets the same job back
    key = f"bk-{policy.pk}-{vm.pk}-{day:%Y%m%d}"
    raw = {"instance": vm.pk, "target": policy.target_id, "frozen": policy.frozen, "policy": policy.pk,
           "deadline": (start + WINDOW).isoformat()}  # a job that waited past it for a worker slot does not start
    try:
        op = jobs.submit("backup.create", policy.owner, raw, key)
    except (claims.Busy, ConnectionFailed):
        return
    except (libvirtError, PermissionDenied, jobs.SubmissionConflict) as err:  # it would be refused again
        _record(policy, vm, day, BackupRun.FAILED, said(err) if str(err) else say(type(err).__name__))
        return
    except Exception as err:
        logger.error("schedule %s: backup of %s not submitted: %s", policy.name, vm.name, safe_text(err))
        return
    _record(policy, vm, day, BackupRun.SUBMITTED, operation=op)


def _attempt_key(base):
    """The submission key of the next attempt of a job named base: the
    running or ended one's own, so it is not submitted twice; a new one an
    hour after a failed or cancelled one; None before that."""
    attempts = Operation.objects.filter(submission_key__startswith=f"{base}-")
    last = attempts.order_by("-created_at").first()
    if last is None:
        return f"{base}-0"
    if last.state not in (Operation.FAILED, Operation.CANCELLED):
        return last.submission_key
    if last.finished_at and timezone.now() - last.finished_at < RETRY_AFTER:
        return None
    return f"{base}-{attempts.count()}"


def retain():
    """Each schedule's backups of a VM beyond keep that no backup builds on,
    oldest first: one
    deletion a target at a time (its claim admits one), the rest at the next
    passes. Backups by hand and those of removed VMs are left alone."""
    tried = set()
    for policy in BackupPolicy.objects.select_related("owner"):
        if policy.target_id in tried or not _active_superuser(policy.owner):
            continue
        vms = (Backup.objects.filter(policy=policy, state=Backup.READY, instance__isnull=False)
               .values_list("instance_id", flat=True).distinct())
        for instance_id in vms:
            # a chain goes when all of it is beyond keep, newest first: only a backup nothing builds on is deleted
            beyond = [b for b in beyond_keep(policy, instance_id) if not b.depended_on()]
            if beyond:
                tried.add(policy.target_id)
                if (key := _attempt_key(f"rt-{beyond[-1].uuid.hex}")) is None:
                    break
                try:
                    jobs.submit("backup.delete", policy.owner, {"backup": str(beyond[-1].uuid), "retention": policy.pk},
                                key)
                except Exception as err:  # busy, or refused: the next pass looks again
                    logger.info("schedule %s: retention waits: %s", policy.name, safe_text(err))
                break


def check_targets(now):
    """A backup.check job for each target not checked today, as the first
    active superuser; a busy target is checked at a later pass."""
    today = timezone.localtime(now).date()
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    if user is None:
        return
    for target in BackupTarget.objects.filter(pools__isnull=False).distinct():
        if target.checked_at and timezone.localtime(target.checked_at).date() >= today:
            continue
        if (key := _attempt_key(f"ck-{target.pk}-{today:%Y%m%d}")) is None:
            continue
        try:
            jobs.submit("backup.check", user, {"target": target.pk}, key)
        except Exception as err:
            logger.info("target %s: check waits: %s", target.name, safe_text(err))
