import json
from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from appsettings.models import AppSettings
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
    logs_per_page = int(AppSettings.objects.get(key="LOGS_PER_PAGE").value)
    limit_from = (page-1) * logs_per_page
    limit_to = page * logs_per_page
    logs = Logs.objects.all().order_by('-date')[limit_from:limit_to+1]
    has_next_page = logs.count() > logs_per_page
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
