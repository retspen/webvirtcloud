import json

from django.http import HttpResponse

from admin.decorators import superuser_only
from instances.models import Instance
from logs.models import Logs


def addlogmsg(user, instance, message):
    """
    :param user:
    :param instance:
    :param message:
    :return:
    """
    add_log_msg = Logs(user=user, instance=instance, message=message)
    add_log_msg.save()


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
        log["instance"] = l.instance
        log["message"] = l.message
        log["date"] = l.date.strftime("%x %X")
        logs.append(log)

    return HttpResponse(json.dumps(logs))
