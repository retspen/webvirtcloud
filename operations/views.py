from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from vrtManager.util import OperationError

from . import jobs as jobs_module
from .api.serializers import OperationSerializer
from .models import Operation, last_seen


def _visible(user):
    return Operation.objects.all() if user.is_superuser else Operation.objects.filter(user=user)


def _get(user, pk):
    try:
        return _visible(user).get(pk=pk)
    except Operation.DoesNotExist:
        raise Http404 from None


def jobs(request):
    qs = _visible(request.user)
    if request.user.is_superuser:
        # the host and the user as typed: the start of the host, any part of the name
        if compute := request.GET.get("compute"):
            qs = qs.filter(resource_label__istartswith=compute)
        if username := request.GET.get("username"):
            qs = qs.filter(username__icontains=username)
        for field in ("state", "kind"):
            if value := request.GET.get(field):
                qs = qs.filter(**{field: value})
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    # the model for its datetimes, the serialized job for its labels
    rows = [(op, OperationSerializer(op, context={"request": request}).data) for op in page.object_list]
    seen = last_seen()
    # a job the worker has to start, run or stop, not one a request runs (job_panel.js uses the same rule)
    unavailable = ((seen is None or timezone.now() - seen > timedelta(seconds=60))
                   and _visible(request.user).filter(state__in=Operation.ACTIVE)
                   .exclude(worker=Operation.REQUEST).exists())
    return render(request, "operations/jobs.html",
                  {"page": page, "rows": rows, "worker_last_seen": seen, "worker_unavailable": unavailable,
                   "filters": request.GET, "active_states": Operation.ACTIVE,
                   "follow": any(op.state in Operation.ACTIVE for op in page.object_list),
                   "states": Operation.ACTIVE + Operation.TERMINAL,
                   "kinds": sorted((name, _(kind.label)) for name, kind in jobs_module.KINDS.items()),
                   "bytes_kinds": {name for name, kind in jobs_module.KINDS.items() if kind.progress_bytes},
                   "page_query": urlencode({k: v for k, v in request.GET.items() if k != "page"})})


def job(request, pk):
    op = _get(request.user, pk)
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
        messages.error(request, str(err))
    return redirect("operations:job", pk=op.pk)


@require_POST
def resolve(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    op = _get(request.user, pk)
    try:
        jobs_module.resolve(op.pk, request.user, request.POST.get("outcome", ""), request.POST.get("note", ""))
    except OperationError as err:
        messages.error(request, str(err))
    return redirect("operations:job", pk=op.pk)
