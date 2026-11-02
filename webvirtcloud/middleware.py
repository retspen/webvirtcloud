from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError
from operations import claims, jobs
from operations.utils import busy_message, public_error_text, summary

API_PREFIX = "/api/"
# scripts only from this site: no inline script or event handler runs (inline styles still do);
# the XML editor (Ace) and the API docs (Redoc) start their workers from blob: URLs
CONTENT_SECURITY_POLICY = (
    "script-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)


def same_origin_referer(request, default):
    """The Referer without its fragment if it is on this site, else default."""
    referer = request.META.get("HTTP_REFERER")
    if referer and url_has_allowed_host_and_scheme(
        url=referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return referer.split("#")[0]
    return default


def error_text(request, exception):
    """
    The libvirt error to show. Administrators (superusers and the global
    view_instances permission, who see the hosts) get the full error; other
    users the public text.
    """
    user = getattr(request, "user", None)
    if user and (user.is_superuser or user.has_perm("instances.view_instances")):
        return str(exception)
    return public_error_text(exception)


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response


class ExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # API clients get JSON with a failure status, not the HTML error page.
        if request.path_info.startswith(API_PREFIX):
            if isinstance(exception, libvirtError):
                return JsonResponse({"detail": error_text(request, exception)}, status=400)
            if isinstance(exception, claims.Busy):
                return JsonResponse({"detail": busy_message(exception, request.user),
                                     "operation": summary(exception.blocker, request.user) if exception.blocker else None},
                                    status=409)
            if isinstance(exception, jobs.SubmissionConflict):
                return JsonResponse({"detail": str(exception)}, status=409)
            if isinstance(exception, TimeoutError):
                return JsonResponse({"detail": "Operation is busy. Please retry."}, status=409)
            return None
        if isinstance(exception, claims.Busy) and request.method not in ("GET", "HEAD"):
            # back to the form with the reason; a GET is never redirected to itself
            messages.error(request, busy_message(exception, request.user))
            return redirect(request.get_full_path())
        if isinstance(exception, libvirtError):
            messages.error(
                request,
                _("libvirt Error - %(exception)s") % {"exception": error_text(request, exception)},
            )
            if request.method not in ("GET", "HEAD"):
                # a refused form: back to the page it was on, with the reason
                return redirect(same_origin_referer(request, "/"))
            return render(request, "500.html", {"libvirt_error": True}, status=500)
            # TODO: check connecting to host via VPN
