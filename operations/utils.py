"""Secrets never reach a job record, a response or a log line, and users who
do not see the hosts get "host unreachable" instead of a connection error's
text (which names the host). What a refused request says about the job holding
the resource: details for its owner and superusers, a minimal summary for
everyone else; and who may see jobs on a resource page. Worker settings from
the Settings page. The worker reads them itself (the settings middleware only
runs in gunicorn)."""

import re

import libvirt
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.translation import gettext as _
from django.utils.translation import pgettext
from django.utils.translation import gettext_noop
from libvirt import libvirtError

from accounts.models import UserInstance
from appsettings.models import AppSettings
from instances.models import Instance
from vrtManager.util import ConnectionFailed, OperationError

from . import jobs

_NAMES = r"(?:pass|secret|token|key)\w*"
_PATTERNS = [
    (re.compile(r"(://[^:/@\s]+:)[^@\s]+@"), r"\1***@"),
    # quoted values, also XML attributes: passwd='x', password="x"
    (re.compile(rf"""({_NAMES}['"]?\s*[:=]\s*)(['"])(?:\\.|(?!\2)[^\\])*\\?(?:\2|\Z)""", re.I | re.S), r"\1\2***\2"),
    (re.compile(rf"""({_NAMES}['"]?\s*[:=]\s*)[^\s'",;<>]+""", re.I), r"\1***"),
    # <secret ...>value</secret>-like elements
    (re.compile(r"(<(secret|passphrase)\b[^>]*>).*?(</\2>)", re.I | re.S), r"\1***\3"),
]
_SECRET_KEY = re.compile(r"pass|secret|token|private|key$", re.I)

# errors of the connection to the host, not of the operation: both the
# domain and the code must match (a daemon that lacks a procedure answers
# VIR_FROM_RPC / VIR_ERR_NO_SUPPORT, which the user should see)
TRANSPORT_ERROR_DOMAINS = {libvirt.VIR_FROM_RPC, libvirt.VIR_FROM_REMOTE, libvirt.VIR_FROM_SSH, libvirt.VIR_FROM_LIBSSH}
TRANSPORT_ERROR_CODES = {
    libvirt.VIR_ERR_INTERNAL_ERROR,  # "connection closed due to keepalive timeout"
    libvirt.VIR_ERR_SYSTEM_ERROR,  # "Cannot recv data: ..."
    libvirt.VIR_ERR_RPC,
    libvirt.VIR_ERR_NO_CONNECT,
    libvirt.VIR_ERR_AUTH_FAILED,
    libvirt.VIR_ERR_AUTH_UNAVAILABLE,
    libvirt.VIR_ERR_AUTH_CANCELLED,
    libvirt.VIR_ERR_SSH,
    libvirt.VIR_ERR_LIBSSH,
}
UNREACHABLE = gettext_noop("The host of this virtual machine cannot be reached right now.")

BOUNDS = {"WORKER_CONCURRENCY": (1, 16, 4), "JOB_RETENTION_DAYS": (1, 3650, 30)}


def safe_text(text):
    text = str(text)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# A text a job keeps for later (its error, its result's warning) is a list of
# messages, each our English text, marked with gettext_noop, and its values:
# words() puts them in the language of whoever reads them. A text that is not
# ours (libvirt's) is a message without values and stays as it is.
def say(text, **values):
    return [{"text": safe_text(text), "values": {key: safe_text(value) for key, value in values.items()}}]


def said(exception):
    """The messages of an exception: an OperationError's text and values, else its text."""
    if isinstance(exception, OperationError):
        return say(exception.text, **exception.values)
    return say(exception)


def words(messages):
    """messages in the active language, each a sentence of its own."""
    parts = [_(m["text"]) % m["values"] if m["values"] else _(m["text"]) for m in messages]
    return " ".join(part if last or part.endswith((".", "。", "!", "?")) else part + "."
                    for last, part in ((i == len(parts) - 1, part) for i, part in enumerate(parts)))


def public_error(exception):
    """The error for users who do not see the hosts: a connection error names
    the host and how it is reached, so they learn only that it cannot be reached."""
    connection_error = isinstance(exception, ConnectionFailed) or (
        isinstance(exception, libvirtError)
        and exception.get_error_domain() in TRANSPORT_ERROR_DOMAINS
        and exception.get_error_code() in TRANSPORT_ERROR_CODES
    )
    return say(UNREACHABLE) if connection_error else said(exception)


def public_error_text(exception):
    return words(public_error(exception))


def check_params(params):
    if isinstance(params, dict):
        for key, value in params.items():
            if _SECRET_KEY.search(str(key)):
                raise ValueError(f"A job cannot store the field {key}")
            check_params(value)
    elif isinstance(params, (list, tuple)):
        for value in params:
            check_params(value)


def may_see(op, user):
    return user.is_superuser or (op.user_id is not None and op.user_id == user.pk)


def shown_label(op, user):
    """The job's "<compute>/<vm>" label, without the compute for users the app hides hosts from.
    A compute name may contain "/", a VM name may not (libvirt refuses it)."""
    if user.is_superuser or user.has_perm("instances.view_instances"):
        return op.resource_label
    return op.resource_label.rsplit("/", 1)[-1]


def visible(user, key):
    if user.is_superuser:
        return True
    kind, _sep, rest = key.partition(":")
    if kind != "instance":
        return False  # compute, storage and network pages are superuser-only
    instances = Instance.objects.filter(uuid=rest)
    if user.has_perm("instances.view_instances"):
        return instances.exists()
    return UserInstance.objects.filter(user=user, instance__in=instances).exists()


def summary(op, user):
    base = {"kind": op.kind, "label": str(_(jobs.label_of(op.kind))), "state": op.state, "since": op.created_at}
    if may_see(op, user):
        base.update({"id": str(op.id), "user": op.username})
    return base


def busy_message(busy, user):
    op = busy.blocker
    if op is None:
        return _("A short operation is in progress on this resource; try again in a moment.")
    values = {"label": _(jobs.label_of(op.kind)), "state": pgettext("job state", op.state), "since": timesince(op.created_at, timezone.now())}
    if may_see(op, user):
        return _("%(label)s is %(state)s on this resource (started by %(user)s, %(since)s ago); "
                 "see the Jobs page.") % {**values, "user": op.username}
    return _("%(label)s is %(state)s on this resource (since %(since)s).") % values


def _value(key):
    low, high, default = BOUNDS[key]
    try:
        value = int(AppSettings.objects.get(key=key).value)
    except (AppSettings.DoesNotExist, ValueError):
        return default
    return value if low <= value <= high else default


def concurrency():
    return _value("WORKER_CONCURRENCY")


def retention_days():
    return _value("JOB_RETENTION_DAYS")
