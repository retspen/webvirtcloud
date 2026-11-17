from django.contrib import messages
from django.db import transaction
from django.conf import settings
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from libvirt import libvirtError

from admin.decorators import superuser_only
from instances.models import Instance
from logs.audit import audit
from operations import claims, jobs
from operations.utils import busy_message
from webvirtcloud.middleware import error_text, same_origin_referer
from vrtManager.backup import pool_space, target_pool
from vrtManager.connection import wvmConnect
from vrtManager.util import OperationError

from .forms import PolicyForm, RestoreForm, TargetForm, TargetPoolForm
from .models import Backup, BackupPolicy, BackupTarget
from .utils import inside_vm_pool


def connect(compute):
    return wvmConnect(compute.hostname, compute.login, compute.password, compute.type)


@superuser_only
def targets(request):
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
            return redirect("vmbackups:target", target.id)
    rows = BackupTarget.objects.annotate(backup_count=Count("backups")).prefetch_related("pools__compute").order_by("name")
    return render(request, "vmbackups/targets.html", {"targets": rows, "form": form})


def pool_state(row):
    """A target's pool on its compute as the page shows it: its space and
    whether another pool holds it, or why it cannot be read."""
    try:
        conn = connect(row.compute)
        pool = target_pool(conn, row.pool, row.pool_uuid)
        return {"row": row, "space": pool_space(pool), "inside": inside_vm_pool(conn, pool)}
    except libvirtError as err:
        return {"row": row, "error": str(err)}


@superuser_only
def target(request, target_id):
    target = get_object_or_404(BackupTarget, pk=target_id)
    subject = f"Backup target {target.name}"
    form = TargetPoolForm(request.POST if "add_pool" in request.POST else None, target=target)
    if request.method == "POST" and "delete" in request.POST:
        if target.backups.exists():
            messages.error(request, _("Backup target %(target)s has backups; delete them first") % {"target": target.name})
            return redirect("vmbackups:target", target.id)
        if target.policies.exists():
            messages.error(request, _("Backup target %(target)s has schedules; delete them first") % {"target": target.name})
            return redirect("vmbackups:target", target.id)
        with audit(request, None, subject, "delete"):
            target.delete()
        return redirect("vmbackups:targets")
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
    if request.method == "POST" and "remove_pool" in request.POST:
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
    pools = [pool_state(row) for row in target.pools.select_related("compute").order_by("compute__name")]
    return render(request, "vmbackups/target.html", {"target": target, "pools": pools, "form": form,
                                                     "backup_count": target.backups.count()})


@require_POST
@superuser_only
def create(request, instance_id):
    """Back up now, from the VM's Backups tab: a backup.create job."""
    instance = get_object_or_404(Instance, pk=instance_id)
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
def index(request):
    """Every backup, newest first; filtered by VM name, target and state."""
    rows = Backup.objects.select_related("target", "instance", "policy")
    vm, target, state = request.GET.get("vm", "").strip(), request.GET.get("target", ""), request.GET.get("state", "")
    if vm:
        rows = rows.filter(vm_name__icontains=vm)
    if target.isdigit():
        rows = rows.filter(target_id=int(target))
    if state in dict(Backup.STATES):
        rows = rows.filter(state=state)
    return render(request, "vmbackups/index.html", {
        "rows": rows, "targets": BackupTarget.objects.order_by("name"),
        "vm": vm, "target": target, "state": state,
    })


@require_POST
@superuser_only
def delete(request, uuid):
    backup = get_object_or_404(Backup, uuid=uuid)
    try:
        op = jobs.submit("backup.delete", request.user, {"backup": str(backup.uuid)},
                         request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        messages.error(request, busy_message(busy, request.user))
    except (jobs.SubmissionConflict, libvirtError) as err:
        messages.error(request, error_text(request, err))
    else:
        # the job's page follows it: the pages listing backups show no backup's job
        return redirect("operations:job", op.pk)
    return redirect(same_origin_referer(request, reverse("vmbackups:index")))


@superuser_only
def restore(request, uuid):
    """Restore a ready backup as a new VM: a backup.restore job, followed on its page."""
    backup = get_object_or_404(Backup.objects.select_related("target"), uuid=uuid, state=Backup.READY)
    form = RestoreForm(request.POST or None, backup=backup)
    if form.is_valid():
        data = form.cleaned_data
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
    return render(request, "vmbackups/restore.html", {"backup": backup, "form": form})


@superuser_only
def policies(request):
    """The backup schedules, and a new one; the superuser who saves one is its owner, whom its jobs run as."""
    form = PolicyForm(request.POST or None)
    if form.is_valid():
        with audit(request, None, f"Backup schedule {form.cleaned_data['name']}", "add"):
            policy = form.save(commit=False)
            policy.owner = request.user
            policy.save()
            form.save_m2m()
        return redirect("vmbackups:policy", policy.pk)
    rows = BackupPolicy.objects.select_related("target", "compute", "owner").annotate(vm_count=Count("instances"))
    return render(request, "vmbackups/policies.html", {"policies": rows.order_by("name"), "form": form,
                                                       "time_zone": settings.TIME_ZONE})


@superuser_only
def policy(request, policy_id):
    policy = get_object_or_404(BackupPolicy.objects.select_related("target", "compute", "owner"), pk=policy_id)
    subject = f"Backup schedule {policy.name}"
    if request.method == "POST" and "delete" in request.POST:
        with audit(request, None, subject, "delete"):  # its backups stay, without a schedule
            policy.delete()
        return redirect("vmbackups:policies")
    form = PolicyForm(request.POST or None, instance=policy)
    if form.is_valid():
        with audit(request, None, subject, "change"):
            policy = form.save(commit=False)
            policy.owner = request.user
            policy.save()
            form.save_m2m()
        return redirect("vmbackups:policy", policy.pk)
    runs = policy.runs.select_related("instance", "operation").order_by("-day", "instance__name")[:200]
    return render(request, "vmbackups/policy.html", {"policy": policy, "form": form, "runs": runs,
                                                     "time_zone": settings.TIME_ZONE})
