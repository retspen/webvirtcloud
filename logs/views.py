from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from logs.models import Logs


def showlogs(request):
    return render(request, 'showlogs.html', locals())