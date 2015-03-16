from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from logs.models import Logs


def showlogs(request):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    logs = Logs.objects.all()

    return render(request, 'showlogs.html', locals())