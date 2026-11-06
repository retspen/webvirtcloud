import re
import uuid

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
import libvirt
from libvirt import libvirtError
from logs.audit import request_ip, write
from operations import claims, jobs
from operations.utils import busy_message, public_error_text, said, summary, words

from vrtManager.util import ConnectionFailed, InUse
from webvirtcloud.log_context import current_request

API_PREFIX = "/api/"
# nginx's $request_id; any other value is replaced, so a client cannot write into the log
REQUEST_ID = re.compile(r"[0-9a-f]{32}")
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
        return words(said(exception))
    return public_error_text(exception)


# libvirt's "no such object" errors
NOT_FOUND_CODES = {
    libvirt.VIR_ERR_NO_DOMAIN, libvirt.VIR_ERR_NO_DOMAIN_SNAPSHOT, libvirt.VIR_ERR_NO_STORAGE_POOL,
    libvirt.VIR_ERR_NO_STORAGE_VOL, libvirt.VIR_ERR_NO_NETWORK, libvirt.VIR_ERR_NO_INTERFACE,
    libvirt.VIR_ERR_NO_NWFILTER, libvirt.VIR_ERR_NO_SECRET, libvirt.VIR_ERR_NO_NODE_DEVICE,
}


def api_status(request, exception):
    """An API client's status for a libvirt error: 404 for an object the host
    does not have, 409 for one in use, 503 for a host that cannot be reached
    (a client may try again), else 400. Only a read or a delete names the
    object not found: an action (POST) may miss another one it needs, as a
    VM's removed network, and the VM is there."""
    if isinstance(exception, InUse):
        return 409
    if isinstance(exception, ConnectionFailed):
        return 503
    if request.method in ("GET", "HEAD", "DELETE") and exception.get_error_code() in NOT_FOUND_CODES:
        return 404
    return 400


class RequestIdMiddleware:
    """Names the request for its log lines (see log_context) and sends the ID back in X-Request-ID."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID", "")
        request.request_id = request_id if REQUEST_ID.fullmatch(request_id) else uuid.uuid4().hex
        request.client_ip = request_ip(request)
        # not reset after the response: Django logs a 4xx or 5xx answer after the middleware returns
        current_request.set(request)
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response


class AccessDeniedMiddleware:
    """
    A Logs row for each 401 or 403 answered to a signed-in user or to a request
    with credentials (an API token). Anonymous requests are left out: a
    scanner would fill the table.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code in (401, 403):
            user = getattr(request, "user", None)
            signed_in = user is not None and user.is_authenticated
            if signed_in or "Authorization" in request.headers:
                write(user.get_username() if signed_in else "", "-", "",
                      f"Access denied ({response.status_code}): {request.method} {request.path}", False,
                      request_ip(request))
        return response


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
                return JsonResponse({"detail": error_text(request, exception)}, status=api_status(request, exception))
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
