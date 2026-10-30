from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from admin.decorators import superuser_only
from instances.models import Instance
from logs.models import Logs

# the rows of a VM on its Stats tab; the Logs page has them all
VM_LOG_ROWS = 50


@superuser_only
def vm_logs(request, pk):
    """The rows of a VM, found by its UUID: a rename keeps them, and a VM on two computes is one VM."""
    vm = get_object_or_404(Instance, pk=pk)
    results = {None: _("Unknown"), True: _("Done"), False: _("Failed")}
    logs = []
    for log in Logs.objects.filter(instance_uuid=vm.uuid).order_by("-date", "-id")[:VM_LOG_ROWS]:
        logs.append({
            "user": log.user,
            "host": log.host,
            "instance": log.instance,
            "message": log.message,
            "result": results[log.success],
            "date": log.date.strftime("%x %X"),
        })
    return JsonResponse(logs, safe=False)
