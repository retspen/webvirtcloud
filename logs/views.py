from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from instances.models import Instance
from logs.models import Logs
from django.conf import settings
import json


def addlogmsg(user, instance, message):
    """
    :param user:
    :param instance:
    :param message:
    :return:
    """
    add_log_msg = Logs(user=user, instance=instance, message=message)
    add_log_msg.save()


@login_required
def showlogs(request, page=1):
    """
    :param request:
    :param page:
    :return:
    """

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    page = int(page)
    limit_from = (page-1)*settings.LOGS_PER_PAGE
    limit_to = page*settings.LOGS_PER_PAGE
    logs = Logs.objects.all().order_by('-date')[limit_from:limit_to+1]
    has_next_page = logs.count() > settings.LOGS_PER_PAGE
    # TODO: remove last element from queryset, but do not affect database

    return render(request, 'showlogs.html', locals())


@login_required
def vm_logs(request, vname):
    """
    :param request:
    :param vname:
    :return:
    """
    
    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    vm = Instance.objects.get(name=vname)
    logs_ = Logs.objects.filter(instance=vm.name, date__gte=vm.created).order_by('-date')
    logs = []
    for l in logs_:
        log = dict()
        log['user'] = l.user
        log['instance'] = l.instance
        log['message'] = l.message
        log['date'] = l.date.strftime('%x %X')
        logs.append(log)
    
    return HttpResponse(json.dumps(logs))
