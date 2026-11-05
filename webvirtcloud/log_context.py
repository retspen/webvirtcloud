"""Each log line of a web request names the request, its user and its client
address (set by webvirtcloud.middleware.RequestIdMiddleware)."""

import contextvars
import logging

current_request = contextvars.ContextVar("current_request", default=None)


class RequestFilter(logging.Filter):
    """Adds request_id, user and ip to each record; "-" outside a web request."""

    def filter(self, record):
        request = current_request.get()
        record.request_id = getattr(request, "request_id", "-")
        record.ip = getattr(request, "client_ip", None) or "-"
        record.user = "-"
        try:
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                record.user = user.get_username()
        except Exception:  # the user may be read from the database here; a failure must not lose the line
            pass
        return True


class NotFoundFilter(logging.Filter):
    """Leaves out django.request's line for a 404: scanners and old links
    would bury the lines that matter."""

    def filter(self, record):
        return getattr(record, "status_code", None) != 404
