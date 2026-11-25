import re
import uuid

from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import middleware as auth_middleware
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views import csrf
import libvirt
from libvirt import libvirtError
from logs.audit import request_ip, write
from operations import claims, jobs
from operations.utils import busy_message, public_error_text, said, summary, words

from vrtManager.util import ConnectionFailed, InUse, OperationError
from webvirtcloud import log_context
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


class LoginRequiredMiddleware(auth_middleware.LoginRequiredMiddleware):
    """Django's, for a session that ended while a page was open. A page's script asking (an XHR)
    gets 401, which session_end.js tells the user about, not the sign-in page. A form sent (a POST)
    is not asked for again by GET after the sign-in, where its view would answer 405: the sign-in
    goes back to the page the form was on, and says it was not done."""

    def handle_no_permission(self, request, view_func):
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return HttpResponse(status=401)
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return super().handle_no_permission(request, view_func)
        messages.info(request, _("You were signed out, so it was not done: sign in and do it again."))
        page = urlsplit(same_origin_referer(request, "/"))
        # a form shown again at its own address (one with errors): that answers POST only
        back = "/" if page.path == request.path else page.path + (f"?{page.query}" if page.query else "")
        return redirect_to_login(back, resolve_url(self.get_login_url(view_func)), self.get_redirect_field_name(view_func))


def csrf_failure(request, reason=""):
    """A form sent with a token no longer good. After a session ended (a sign-in elsewhere
    gives a new token), as LoginRequiredMiddleware does for it; else, and for the sign-in
    form itself, Django's 403."""
    if not request.user.is_authenticated and request.path != resolve_url(settings.LOGIN_URL):
        return LoginRequiredMiddleware(lambda request: None).handle_no_permission(request, None)
    return csrf.csrf_failure(request, reason)


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
        token = log_context.request_ip.set(request.client_ip)
        try:
            response = self.get_response(request)
        finally:
            log_context.request_ip.reset(token)
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
            text = error_text(request, exception)
            # the panel's own refusal (OperationError) is not libvirt's error
            messages.error(request, text if isinstance(exception, OperationError)
                           else _("libvirt Error - %(exception)s") % {"exception": text})
            if request.method not in ("GET", "HEAD"):
                # a refused form: back to the page it was on, with the reason
                return redirect(same_origin_referer(request, "/"))
            if exception.get_error_code() in NOT_FOUND_CODES:
                # removed on the host, as a VM undefined in virsh: not a fault of the panel
                return render(request, "404.html", {"request_path": request.path}, status=404)
            return render(request, "500.html", {"libvirt_error": True}, status=500)
            # TODO: check connecting to host via VPN


class DisableCSRFMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        setattr(request, '_dont_enforce_csrf_checks', True)
        response = self.get_response(request)
        return response
