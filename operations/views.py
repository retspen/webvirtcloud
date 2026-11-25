from collections import Counter
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import Error as DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from vrtManager.util import OperationError

from computes.models import Compute
from instances.models import Instance
from vmbackups.models import BackupTarget

from . import jobs as jobs_module
from .api.serializers import OperationSerializer
from .models import Operation, last_seen, worker_gone
from .utils import said, words


def _get(user, pk):
    try:
        return Operation.visible_to(user).get(pk=pk)
    except Operation.DoesNotExist:
        raise Http404 from None


def jobs(request):
    qs = Operation.visible_to(request.user)
    if request.user.is_superuser:
        # the host and the user as typed: the start of the host, any part of the name
        if compute := request.GET.get("compute"):
            qs = qs.filter(resource_label__istartswith=compute)
        if username := request.GET.get("username"):
            qs = qs.filter(username__icontains=username)
    # a state or kind for every user: the VM list sends its owners to their power jobs
    for field in ("state", "kind"):
        if value := request.GET.get(field):
            qs = qs.filter(**{field: value})
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    link_resources(request.user, page.object_list)
    # the model for its datetimes, the serialized job for its labels
    rows = [(op, OperationSerializer(op, context={"request": request}).data) for op in page.object_list]
    seen = last_seen()
    # a job the worker has to start, run or stop, not one a request runs (job_panel.js uses the same rule)
    unavailable = (worker_gone(seen)
                   and Operation.visible_to(request.user).filter(state__in=Operation.ACTIVE)
                   .exclude(worker=Operation.REQUEST).exists())
    return render(request, "operations/jobs.html",
                  {"page": page, "rows": rows, "worker_last_seen": seen, "worker_unavailable": unavailable,
                   "filters": request.GET, "active_states": Operation.ACTIVE,
                   "filtered": any(request.GET.get(field) for field in ("compute", "username", "state", "kind")),
                   "follow": any(op.state in Operation.ACTIVE for op in page.object_list),
                   "states": Operation.ACTIVE + Operation.TERMINAL,
                   "kinds": sorted((name, _(kind.label)) for name, kind in jobs_module.KINDS.items()),
                   "bytes_kinds": {name for name, kind in jobs_module.KINDS.items() if kind.progress_bytes},
                   "page_query": urlencode({k: v for k, v in request.GET.items() if k != "page"})})


def link_resources(user, ops):
    """Gives each job the page of what it works on (op.resource_url, or None): a VM's for who may
    see the VM (one of a UUID only: a copy on another host has it too); a host's, a backup
    target's, or the Computes page for a bulk migration, for a superuser. A thing gone has none.
    A backup's or a pool's job has none: a restore names the new VM, a pool may be gone."""
    parts = [op.resource.partition(":")[::2] for op in ops]
    named = lambda kind: [rest for each, rest in parts if each == kind]
    seen_all = user.is_superuser or user.has_perm("instances.view_instances")
    vms = Instance.objects.all() if seen_all else Instance.objects.filter(userinstance__user=user)
    found = list(vms.filter(uuid__in=named("instance")).values_list("uuid", "pk"))
    once = [uuid for uuid, n in Counter(uuid for uuid, _pk in found).items() if n == 1]
    vm_of = {uuid: pk for uuid, pk in found if uuid in once}
    hosts = targets = set()
    if user.is_superuser:
        hosts = {str(pk) for pk in Compute.objects.filter(pk__in=[r for r in named("compute") if r.isdigit()])
                 .values_list("pk", flat=True)}
        targets = {str(pk) for pk in BackupTarget.objects.filter(pk__in=[r for r in named("backup_target") if r.isdigit()])
                   .values_list("pk", flat=True)}
    for op, (kind, rest) in zip(ops, parts):
        op.resource_url = _resource_url(kind, rest, vm_of, hosts, targets, user.is_superuser)


def _resource_url(kind, rest, vm_of, hosts, targets, superuser):
    """The page of a job's resource, kind:rest (operations.claims), among those link_resources found."""
    if kind == "instance" and rest in vm_of:
        return reverse("instances:instance", args=[vm_of[rest]])
    if kind == "compute" and rest in hosts:
        return reverse("overview", args=[rest])
    if kind == "backup_target" and rest in targets:
        return reverse("vmbackups:target", args=[rest])
    if kind == "bulk_migrate" and superuser:
        return reverse("computes")
    return None


def job(request, pk):
    op = _get(request.user, pk)
    link_resources(request.user, [op])
    kind = jobs_module.KINDS.get(op.kind)
    return render(request, "operations/job.html",
                  {"job": OperationSerializer(op, context={"request": request}).data, "op": op,
                   "progress_bytes": kind is not None and kind.progress_bytes,
                   "follow": op.state in Operation.ACTIVE})


@require_POST
def cancel(request, pk):
    op = _get(request.user, pk)
    try:
        jobs_module.cancel(op.pk, request.user)
    except OperationError as err:
        messages.error(request, words(said(err)))
    return redirect("operations:job", pk=op.pk)


@require_POST
def resolve(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    op = _get(request.user, pk)
    try:
        jobs_module.resolve(op.pk, request.user, request.POST.get("outcome", ""), request.POST.get("note", ""))
    except OperationError as err:
        messages.error(request, words(said(err)))
    return redirect("operations:job", pk=op.pk)


@login_not_required
@never_cache
def healthz(request):
    """For a monitor, without a login: 200 while the database answers and the job worker runs, 503 otherwise."""
    try:
        seen = last_seen()
    except DatabaseError:
        return JsonResponse({"database": False, "worker": False}, status=503)
    running = not worker_gone(seen)
    return JsonResponse({"database": True, "worker": running, "worker_seen": seen and seen.isoformat()},
                        status=200 if running else 503)
