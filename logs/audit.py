import ipaddress
import logging
from contextlib import contextmanager
from dataclasses import dataclass

import libvirt
from django.db import transaction

from accounts.lockout import client_ip
from logs.models import Logs

logger = logging.getLogger("logs.audit")


def write(user, host, instance, message, success=None, ip=None):
    """
    Save one Logs row. A failure is written to the log file instead and never
    raised, so an audit write cannot break the action it records.
    """
    user, host, instance = user[:150], host[:255], instance[:120]
    try:
        with transaction.atomic():
            Logs.objects.create(user=user, host=host, instance=instance, message=message, success=success, ip=ip)
    except Exception as e:
        try:
            line = f"audit row not saved ({e!r}): {user} {host} {instance} success={success} ip={ip} {message}"
            logger.warning(line.replace("\n", "\\n"))
        except Exception:
            pass


def request_ip(request):
    """The client address of the request, or None if it is empty or not a plain IP address."""
    value = client_ip(request)
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    # a scoped IPv6 address (fe80::1%eth0) is valid for ipaddress but not for GenericIPAddressField
    return None if "%" in value else value


@dataclass
class Entry:
    action: str
    skip: bool = False


def host_of(compute):
    """The host column for a Compute, or for a host name already at hand."""
    if compute is None:
        return "-"
    return compute if isinstance(compute, str) else compute.name


def reason(exc, user):
    """Why an action failed, as text for the audit row; unknown errors give only their class name."""
    from operations import claims
    from operations.utils import busy_message, safe_text
    from vrtManager.util import OperationError

    if isinstance(exc, claims.Busy):
        return busy_message(exc, user)
    if isinstance(exc, OperationError):
        return str(exc)
    if isinstance(exc, libvirt.libvirtError):
        return safe_text(exc.get_error_message() or str(exc))[:500]
    return type(exc).__name__


@contextmanager
def audit(request, compute, subject, action, instance=""):
    """
    Write one row when the block ends: done, or failed with the reason when it
    raises (the exception goes on). The block may set entry.action, or
    entry.skip when nothing was done.
    """
    entry = Entry(action)
    user, host, ip = request.user.get_username(), host_of(compute), request_ip(request)
    try:
        yield entry
    except Exception as exc:
        write(user, host, instance, f"{subject}: {entry.action}: {reason(exc, request.user)}", False, ip)
        raise
    if not entry.skip:
        write(user, host, instance, f"{subject}: {entry.action}", True, ip)


def failed(request, compute, subject, action, why, instance=""):
    """Write the failure row of an action that was refused before it started."""
    write(request.user.get_username(), host_of(compute), instance, f"{subject}: {action}: {why}", False, request_ip(request))


def snapshot(obj):
    """The field values of a model object, for changed_fields; a many-to-many field gives its related pks."""
    values = {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields}
    for f in obj._meta.many_to_many:
        values[f.name] = frozenset(o.pk for o in getattr(obj, f.name).all()) if obj.pk else frozenset()
    return values


def changed_fields(before, after):
    """The sorted names of the fields whose values differ between two snapshots."""
    return sorted(key.removesuffix("_id") for key in before if before[key] != after[key])
