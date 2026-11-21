"""
Settings for django-axes and the session length, read from the Settings page
(AppSettings) on each use, so an administrator can change them without a
restart.
"""

from datetime import timedelta
from ipaddress import ip_address, ip_network

from appsettings.models import AppSettings
from axes.models import AccessAttempt
from django.conf import settings
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

DEFAULT_FAILURE_LIMIT = 5
DEFAULT_LOCKOUT_MINUTES = 15
DEFAULT_SESSION_HOURS = 24


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


def lockout_response(request, original_response, credentials):
    """AXES_LOCKOUT_CALLABLE: the locked sign-in page, with the lock time."""
    minutes = cooloff_time(request) // timedelta(minutes=1)
    return render(request, "accounts/lockout.html", {"minutes": minutes}, status=429)


def locked_usernames():
    """The usernames, in lower case, locked now from some address. As django-axes
    counts them, a username's recent failures from one address add up over
    the browsers they came from."""
    since = timezone.now() - cooloff_time(None)
    per_address = (AccessAttempt.objects.filter(attempt_time__gte=since).values("username", "ip_address")
                   .annotate(failures=Sum("failures_since_start")).filter(failures__gte=failure_limit(None, {})))
    return {row["username"].lower() for row in per_address}


def unlock(username):
    """End the username's locks, from every address and in any letter case;
    returns how many records went."""
    return AccessAttempt.objects.filter(username__iexact=username).delete()[1].get(AccessAttempt._meta.label, 0)


def start_session(sender, request, user, **kwargs):
    """user_logged_in: a session ends LOGIN_SESSION_HOURS after the sign-in (a
    date, as a number of seconds would count again from each session save)."""
    hours = _positive_int("LOGIN_SESSION_HOURS", DEFAULT_SESSION_HOURS)
    request.session.set_expiry(timezone.now() + timedelta(hours=hours))
