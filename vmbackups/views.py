import datetime
from collections import Counter
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from libvirt import libvirtError
from lxml import etree

from admin.decorators import superuser_only
from computes.models import Compute
from instances.jobs import unprotected
from instances.models import Instance, InstanceTombstone
from instances.views import get_instance
from logs.audit import audit
from operations import claims, jobs
from operations.models import Claim
from operations.utils import busy_message
from webvirtcloud.middleware import error_text, same_origin_referer
from vrtManager.backup import pool_space, target_pool
from vrtManager.connection import wvmConnect
from vrtManager.util import OperationError

from .forms import PolicyForm, RestoreDiskForm, RestoreForm, TargetForm, TargetPoolForm
from .jobs import _over_names, _over_plan, _proxy, _vm_pool
from .models import Backup, BackupPolicy, BackupRun, BackupTarget
from .utils import inside_vm_pool, pending_deletes


def _may_restore(user, backup):
    """A superuser; or a VM owner with the backup permission who may change
    the backup's VM, on a target open to VM owners (the jobs check again)."""
    if user.is_superuser:
        return
    if backup.instance_id is None or not backup.target.owners or not user.has_perm("instances.backup_instances"):
        raise PermissionDenied
    get_instance(user, backup.instance_id, perm_type="change")


def connect(compute):
    return wvmConnect(compute.hostname, compute.login, compute.password, compute.type)


@superuser_only
def targets(request):
    rows = BackupTarget.objects.annotate(backup_count=Count("backups")).prefetch_related("pools__compute").order_by("name")
    return render(request, "vmbackups/targets.html", {"targets": rows})


@superuser_only
def target_new(request):
    """A new backup target, with its first host's storage pool."""
    form = TargetForm(request.POST or None)
    if form.is_valid():
        data = form.cleaned_data
        try:
            with audit(request, data["compute"], f"Backup target {data['name']}", f"add with storage pool {data['pool']}"):
                pool = target_pool(connect(data["compute"]), data["pool"])
                with transaction.atomic():
                    target = BackupTarget.objects.create(name=data["name"])
                    target.pools.create(compute=data["compute"], pool=data["pool"], pool_uuid=pool.UUIDString())
        except libvirtError as err:
            form.add_error("pool", str(err))
        else:
            messages.success(request, _("Backup target %(name)s is added.") % {"name": target.name})
            return redirect("vmbackups:target", target.id)
    return render(request, "vmbackups/target_new.html", {"form": form})


def pool_state(row):
    """A target's pool on its compute as the page shows it: its space and
    whether another pool holds it, or why it cannot be read."""
    try:
        conn = connect(row.compute)
        pool = target_pool(conn, row.pool, row.pool_uuid)
        return {"row": row, "space": pool_space(pool), "inside": inside_vm_pool(conn, pool)}
    except libvirtError as err:
        return {"row": row, "error": str(err)}


def _change_target(request, target, subject, form):
    """Deletes the target, removes or adds a pool of it, as the form asks;
    the page to go to, or None to show the add form's errors."""
    if "delete" in request.POST:
        if target.backups.exists():
            messages.error(request, _("Backup target %(target)s has backups; delete them first") % {"target": target.name})
            return redirect("vmbackups:target", target.id)
        if target.policies.exists():
            messages.error(request, _("Backup target %(target)s has schedules; delete them first") % {"target": target.name})
            return redirect("vmbackups:target", target.id)
        with audit(request, None, subject, "delete"):
            target.delete()
        return redirect("vmbackups:targets")
    if "remove_pool" in request.POST:
        row = get_object_or_404(target.pools.select_related("compute"), pk=request.POST["remove_pool"])
        if target.backups.exists():
            messages.error(request, _("Backup target %(target)s has backups; delete them first") % {"target": target.name})
        else:
            with audit(request, row.compute, subject, f"remove storage pool {row.pool}"):
                row.delete()
        return redirect("vmbackups:target", target.id)
    if form.is_valid():
        compute, name = form.cleaned_data["compute"], form.cleaned_data["pool"]
        try:
            with audit(request, compute, subject, f"add storage pool {name}"):
                pool = target_pool(connect(compute), name)
                # a target is one directory: the new pool must be the one the others are
                other = target.pools.select_related("compute").first()
                if other and not wvmConnect.same_directory(
                    target_pool(connect(other.compute), other.pool, other.pool_uuid), pool
                ):
                    raise OperationError(
                        gettext_noop(
                            "Storage pool %(pool)s of %(compute)s is not the same directory as "
                            "storage pool %(other)s of %(other_compute)s"
                        ),
                        pool=name,
                        compute=compute.name,
                        other=other.pool,
                        other_compute=other.compute.name,
                    )
                target.pools.create(compute=compute, pool=name, pool_uuid=pool.UUIDString())
        except libvirtError as err:
            form.add_error("pool", str(err))
        else:
            return redirect("vmbackups:target", target.id)
    return None


@superuser_only
def target(request, target_id):
    target = get_object_or_404(BackupTarget, pk=target_id)
    subject = f"Backup target {target.name}"
    form = TargetPoolForm(request.POST if "add_pool" in request.POST else None, target=target)
    if request.method == "POST" and {"delete", "remove_pool", "add_pool"} & set(request.POST):
        # a job into or out of the target holds it: its pools and the target do not change under it
        try:
            with claims.hold({claims.backup_target_key(target.pk): Claim.EXCLUSIVE}):
                if (done := _change_target(request, target, subject, form)) is not None:
                    return done
        except claims.Busy as busy:
            messages.error(request, busy_message(busy, request.user))
            return redirect("vmbackups:target", target.id)
    if request.method == "POST" and "owners" in request.POST:
        target.owners = request.POST["owners"] == "1"
        with audit(request, None, subject, "open to VM owners" if target.owners else "closed to VM owners"):
            target.save(update_fields=["owners"])
        messages.success(request, _("VM owners with the backup permission may now use %(target)s.") % {"target": target.name}
                         if target.owners else _("Only superusers use %(target)s now.") % {"target": target.name})
        return redirect("vmbackups:target", target.id)
    if request.method == "POST" and "import" in request.POST:
        try:
            op = jobs.submit("backup.import", request.user, {"target": target.pk}, request.POST.get("submission_key", ""))
        except claims.Busy as busy:
            messages.error(request, busy_message(busy, request.user))
        except (jobs.SubmissionConflict, libvirtError) as err:
            messages.error(request, error_text(request, err))
        else:
            return redirect("operations:job", op.pk)
        return redirect("vmbackups:target", target.id)
    pools = [pool_state(row) for row in target.pools.select_related("compute").order_by("compute__name")]
    return render(request, "vmbackups/target.html", {"target": target, "pools": pools, "form": form,
                                                     "backup_count": target.backups.count()})


@require_POST
@login_required
def create(request, instance_id):
    """Back up now, from the VM's Backups tab: a backup.create job."""
    instance = get_object_or_404(Instance, pk=instance_id)
    if not request.user.is_superuser:  # before the form is read: the job checks again
        if not request.user.has_perm("instances.backup_instances"):
            raise PermissionDenied
        get_instance(request.user, instance.pk, perm_type="change")
    page = reverse("instances:instance", args=[instance.pk]) + "#backups"
    raw = {"instance": instance.pk, "target": request.POST.get("target", ""), "frozen": request.POST.get("frozen", "")}
    try:
        op = jobs.submit("backup.create", request.user, raw, request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        messages.error(request, busy_message(busy, request.user))
    except (jobs.SubmissionConflict, libvirtError) as err:
        messages.error(request, error_text(request, err))
    except (ValueError, BackupTarget.DoesNotExist):
        messages.error(request, _("Choose a backup target"))
    else:
        jobs.remember_job(request, op)
    return redirect(page)


@superuser_only
def pools(request, compute_id):
    """The compute's active pools that keep disks as files (vrtManager file_pools: where a restore
    copies them), each with its type, for a form's pool suggestions (pool_choices.js); ?types=dir,netfs
    keeps those types only. Read as they are, not refreshed; none from a host not reached."""
    compute = get_object_or_404(Compute, pk=compute_id)
    types = request.GET.get("types", "").split(",")
    try:
        found = [{"name": name, "type": etree.fromstring(pool.XMLDesc(0)).get("type")}
                 for name, (pool, _path) in wvmConnect(compute.hostname, compute.login, compute.password,
                                                       compute.type).file_pools().items()]
    except libvirtError:
        found = []
    return JsonResponse([p for p in sorted(found, key=lambda p: p["name"]) if not types[0] or p["type"] in types], safe=False)


@superuser_only
def index(request):
    """Every backup, newest first; filtered by VM name, target and state."""
    rows = Backup.objects.select_related("target", "instance", "policy", "operation")
    vm, target, state = request.GET.get("vm", "").strip(), request.GET.get("target", ""), request.GET.get("state", "")
    if vm:
        rows = rows.filter(vm_name__icontains=vm)
    if target.isdigit():
        rows = rows.filter(target_id=int(target))
    if state in dict(Backup.STATES):
        rows = rows.filter(state=state)
    elif state == "damaged":  # ready, but a verification found damage
        rows = rows.filter(state=Backup.READY).exclude(damage=[])
    # schedules add a backup of each VM a night: the list is read a page at a time, as the jobs are
    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    # a removed VM's badge links to the Removed VMs page while it is listed there
    removed = set(InstanceTombstone.objects.filter(uuid__in={b.vm_uuid for b in page if not b.instance_id})
                  .values_list("uuid", flat=True))
    for backup in page:
        backup.tombstone = backup.vm_uuid in removed
    return render(request, "vmbackups/index.html", {
        "rows": page.object_list, "page": page, "targets": BackupTarget.objects.order_by("name"),
        "vm": vm, "target": target, "state": state, "pending_deletes": pending_deletes(),
        "page_query": urlencode({k: v for k, v in request.GET.items() if k != "page"}),
    })


@require_POST
@login_required
def delete(request, uuid):
    """Delete a backup: a backup.delete job. The page it was asked from shows
    the backup as being deleted until it is gone."""
    backup = get_object_or_404(Backup, uuid=uuid)
    try:
        jobs.submit("backup.delete", request.user, {"backup": str(backup.uuid)}, request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        messages.error(request, busy_message(busy, request.user))
    except (jobs.SubmissionConflict, libvirtError) as err:
        messages.error(request, error_text(request, err))
    else:
        messages.success(request, _("The backup of %(vm)s taken %(time)s is being deleted.") % {
            "vm": backup.vm_name, "time": timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M")})
    return redirect(same_origin_referer(request, reverse("vmbackups:index")))


@require_POST
@superuser_only
def verify(request, uuid):
    """Verify a backup: a backup.verify job, followed on its page."""
    backup = get_object_or_404(Backup, uuid=uuid)
    try:
        op = jobs.submit("backup.verify", request.user, {"backup": str(backup.uuid)}, request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        messages.error(request, busy_message(busy, request.user))
    except (jobs.SubmissionConflict, libvirtError) as err:
        messages.error(request, error_text(request, err))
    else:
        return redirect("operations:job", op.pk)
    return redirect(same_origin_referer(request, reverse("vmbackups:index")))


@login_required
def restore(request, uuid):
    """Restore a ready backup as a new VM: a backup.restore job, followed on
    its page. A VM owner's goes to the VM's compute and its first disk's pool."""
    backup = get_object_or_404(Backup.objects.select_related("target", "instance__compute"), uuid=uuid,
                               state=Backup.READY)
    _may_restore(request.user, backup)
    place = None
    if not request.user.is_superuser:
        try:
            place = {"compute": backup.instance.compute, "pool": _vm_pool(backup.instance)}
        except (libvirtError, OperationError) as err:
            messages.error(request, error_text(request, err))
            return redirect(reverse("instances:instance", args=[backup.instance_id]) + "#backups")
    form = RestoreForm(request.POST or None, backup=backup, place=place)
    if form.is_valid():
        data = {**form.cleaned_data, **(place or {})}
        raw = {"backup": str(backup.uuid), "compute": data["compute"].pk, "pool": data["pool"], "name": data["name"],
               "connect": data["connect"], "start": data["start"]}
        try:
            op = jobs.submit("backup.restore", request.user, raw, request.POST.get("submission_key", ""))
        except claims.Busy as busy:
            form.add_error(None, busy_message(busy, request.user))
        except (jobs.SubmissionConflict, libvirtError) as err:
            form.add_error(None, error_text(request, err))
        else:
            return redirect("operations:job", op.pk)
    return render(request, "vmbackups/restore.html", {"backup": backup, "form": form, "place": place})


def _submit(request, kind, raw):
    """The job, or None with the reason shown."""
    try:
        return jobs.submit(kind, request.user, raw, request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        messages.error(request, busy_message(busy, request.user))
    except (jobs.SubmissionConflict, libvirtError, OperationError) as err:
        messages.error(request, error_text(request, err))
    return None


@login_required
def restore_over(request, uuid):
    """Restore a ready backup over its own shut-off VM, after the page shows
    which volumes it makes: a backup.restore_over job, followed on its page."""
    backup = get_object_or_404(Backup.objects.select_related("target", "instance__compute"), uuid=uuid,
                               state=Backup.READY, instance__isnull=False)
    _may_restore(request.user, backup)
    if request.method == "POST" and (op := _submit(request, "backup.restore_over", {"backup": str(backup.uuid)})):
        return redirect("operations:job", op.pk)
    over, problem = None, None
    try:
        proxy = _proxy(unprotected(backup.instance))
        over = _over_plan(backup, proxy, owner=not request.user.is_superuser)
        names = _over_names(backup, proxy, over)
    except (OperationError, libvirtError) as err:
        over, problem = None, error_text(request, err)
    disks = [{"dev": dev, "old": over["old"][dev], "pool": pool, "name": names[dev]}
             for dev, pool in sorted(over["disks"].items())] if over else []
    return render(request, "vmbackups/restore_over.html", {"backup": backup, "disks": disks, "over": over,
                                                           "problem": problem})


@superuser_only
def restore_disk(request, uuid):
    """Restore one disk of a ready backup as a new volume: a backup.restore_disk job, followed on its page."""
    backup = get_object_or_404(Backup.objects.select_related("target"), uuid=uuid, state=Backup.READY)
    form = RestoreDiskForm(request.POST or None, backup=backup)
    if form.is_valid():
        data = form.cleaned_data
        raw = {"backup": str(backup.uuid), "dev": data["dev"], "compute": data["compute"].pk, "pool": data["pool"],
               "name": data["name"]}
        if op := _submit(request, "backup.restore_disk", raw):
            return redirect("operations:job", op.pk)
    return render(request, "vmbackups/restore_disk.html", {"backup": backup, "form": form})


HISTORY_DAYS = 14  # the days a schedule's runs are shown for
# a day of a schedule on the list is marked as the first of these its runs came to
WORST_FIRST = (BackupRun.FAILED, BackupRun.SKIPPED, BackupRun.RUNNING, BackupRun.STARTED, BackupRun.SUCCEEDED)
DAY_COUNTS = {BackupRun.SUCCEEDED: _("%(n)s backed up"), BackupRun.RUNNING: _("%(n)s running"),
              BackupRun.STARTED: _("%(n)s started"), BackupRun.FAILED: _("%(n)s failed"),
              BackupRun.SKIPPED: _("%(n)s skipped")}


def history_days():
    """The local days of the run history, the oldest first."""
    today = timezone.localdate()
    return [today - datetime.timedelta(days=n) for n in range(HISTORY_DAYS - 1, -1, -1)]


@superuser_only
def policies(request):
    """The backup schedules, each with what its runs of each day came to."""
    days = history_days()
    counts = {}  # (schedule id, day) -> Counter of outcomes
    runs = (BackupRun.objects.filter(day__range=(days[0], days[-1])).order_by()
            .values_list("policy_id", "day", "state", "operation__state").annotate(n=Count("id")))
    for policy_id, day, state, job_state, n in runs:
        counts.setdefault((policy_id, day), Counter())[BackupRun.outcome_of(state, job_state)] += n
    rows = BackupPolicy.objects.select_related("target", "compute", "tag", "owner").annotate(vm_count=Count("instances"))
    rows = list(rows.order_by("name"))
    for policy in rows:
        policy.history = []
        for day in days:
            day_counts = counts.get((policy.pk, day), Counter())
            worst = next((outcome for outcome in WORST_FIRST if day_counts[outcome]), None)
            text = ", ".join(str(DAY_COUNTS[o] % {"n": day_counts[o]}) for o in WORST_FIRST if day_counts[o])
            policy.history.append({"day": day, "outcome": worst, "text": text})
    return render(request, "vmbackups/policies.html", {"policies": rows, "days": days})


@superuser_only
def policy_new(request):
    """A new backup schedule; the superuser who saves one is its owner, whom its jobs run as."""
    form = PolicyForm(request.POST or None)
    if form.is_valid():
        with audit(request, None, f"Backup schedule {form.cleaned_data['name']}", "add"):
            policy = form.save(commit=False)
            policy.owner = request.user
            policy.save()
            form.save_m2m()
        messages.success(request, _("Backup schedule %(name)s is saved.") % {"name": policy.name})
        return redirect("vmbackups:policies")
    return render(request, "vmbackups/policy_new.html", {"form": form, "time_zone": settings.TIME_ZONE})


@superuser_only
def policy(request, policy_id):
    policy = get_object_or_404(BackupPolicy.objects.select_related("target", "compute", "owner"), pk=policy_id)
    subject = f"Backup schedule {policy.name}"
    if request.method == "POST" and "delete" in request.POST:
        with audit(request, None, subject, "delete"):  # its backups stay, without a schedule
            policy.delete()
        messages.success(request, _("Backup schedule %(name)s is deleted; its backups stay.") % {"name": policy.name})
        return redirect("vmbackups:policies")
    form = PolicyForm(request.POST or None, instance=policy)
    if form.is_valid():
        with audit(request, None, subject, "change"):
            policy = form.save(commit=False)
            policy.owner = request.user
            policy.save()
            form.save_m2m()
        messages.success(request, _("Backup schedule %(name)s is saved.") % {"name": policy.name})
        return redirect("vmbackups:policies")
    days = history_days()
    runs = list(policy.runs.filter(day__range=(days[0], days[-1])).select_related("instance", "operation"))
    cells = {vm: {} for vm in policy.vms()}  # its VMs now, and those it ran for in these days
    for run in runs:
        cells.setdefault(run.instance, {})[run.day] = run
    grid = [(vm, [vm_runs.get(day) for day in days]) for vm, vm_runs in sorted(cells.items(), key=lambda i: i[0].name)]
    problems = sorted((run for run in runs if run.outcome in (BackupRun.FAILED, BackupRun.SKIPPED)),
                      key=lambda run: (run.day, run.instance.name), reverse=True)
    return render(request, "vmbackups/policy.html", {"policy": policy, "form": form, "days": days, "grid": grid,
                                                     "problems": problems, "time_zone": settings.TIME_ZONE})
