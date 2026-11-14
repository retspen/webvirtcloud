"""
Settings for django-axes, read from the Settings page (AppSettings) on each
use, so an administrator can change them without a restart.
"""

from datetime import timedelta
from ipaddress import ip_address, ip_network

from appsettings.models import AppSettings
from django.conf import settings

DEFAULT_FAILURE_LIMIT = 5
DEFAULT_LOCKOUT_MINUTES = 15


def _positive_int(key, default):
    try:
        value = int(AppSettings.objects.get(key=key).value)
    except (AppSettings.DoesNotExist, ValueError):
        return default
    return value if value > 0 else default


def failure_limit(request, credentials):
    """AXES_FAILURE_LIMIT: failed logins allowed before the lock."""
    return _positive_int("LOGIN_FAILURE_LIMIT", DEFAULT_FAILURE_LIMIT)


def cooloff_time(request):
    """AXES_COOLOFF_TIME: how long a lock lasts."""
    return timedelta(minutes=_positive_int("LOGIN_LOCKOUT_MINUTES", DEFAULT_LOCKOUT_MINUTES))


def _from_trusted_proxy(remote):
    try:
        address = ip_address(remote)
    except ValueError:
        return False
    if address.is_loopback:  # the bundled nginx
        return True
    return any(address in ip_network(net, strict=False) for net in getattr(settings, "LOGIN_TRUSTED_PROXIES", []))


def client_ip(request):
    """
    AXES_CLIENT_IP_CALLABLE. Behind the bundled nginx every request comes from
    127.0.0.1 and nginx sets X-Real-IP to the client's address (overwriting
    any sent by the client). The header is used only for requests from that
    proxy, or from the addresses in LOGIN_TRUSTED_PROXIES; from anyone else
    it could be forged to escape a lock.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    real_ip = request.META.get("HTTP_X_REAL_IP", "").strip()
    return real_ip if real_ip and _from_trusted_proxy(remote) else remote
