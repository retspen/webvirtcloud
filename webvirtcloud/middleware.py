from django.contrib import messages
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError


class ExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, libvirtError):
            messages.error(
                request,
                _("libvirt Error - %(exception)s") % {"exception": exception},
            )
            return render(request, "500.html", status=500)
            # TODO: check connecting to host via VPN


class DisableCSRFMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        setattr(request, '_dont_enforce_csrf_checks', True)
        response = self.get_response(request)
        return response
