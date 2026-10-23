import logging

from django.http import JsonResponse

from admin.decorators import superuser_only
from instances.models import Instance
from logs.audit import write
from logs.models import Logs


def addlogmsg(user, host, instance, message):
    """
    :param user:
    :param host:
    :param instance:
    :param message:
    :return:
    """
    write(user, host, instance, str(message))
    logger = logging.getLogger("")
    logger.info(f"{user} {host} {instance} {message}")


@superuser_only
def vm_logs(request, vname):
    """
    :param request:
    :param vname:
    :return:
    """

    vm = Instance.objects.get(name=vname)
    logs_ = Logs.objects.filter(instance=vm.name, date__gte=vm.created).order_by("-date")
    logs = []
    for l in logs_:
        log = dict()
        log["user"] = l.user
        log["host"] = l.host
        log["instance"] = l.instance
        log["message"] = l.message
        log["date"] = l.date.strftime("%x %X")
        logs.append(log)

    return JsonResponse(logs, safe=False)
