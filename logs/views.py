from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from logs.models import Logs
from django.conf import settings


def addlogmsg(user, instance, message):
    """
    :param request:
    :return:
    """
    add_log_msg = Logs(user=user, instance=instance, message=message)
    add_log_msg.save()


def showlogs(request, page=1):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    page = int(page)
    limit_from = (page-1)*settings.LOGS_PER_PAGE
    limit_to = page*settings.LOGS_PER_PAGE
    logs = Logs.objects.all().order_by('-date')[limit_from:limit_to+1]
    has_next_page = logs.count() > settings.LOGS_PER_PAGE
    # TODO: remove last element from queryset, but do not affect database

    return render(request, 'showlogs.html', locals())
