import re
from ipaddress import ip_address

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# one or more dot-separated RFC 1123 labels, optional trailing dot
_hostname = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?")
_login = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")
_name = re.compile(r"[A-Za-z0-9._-]+")


def validate_hostname(value):
    """An IPv4 address or a host name that goes safely into a libvirt
    connection URI. No scheme, port, path, query, whitespace or IPv6 literal:
    those would change the URI (an injected ?command=, ?no_verify=, a port or
    a userinfo separator). IPv6 is rejected until the URI building brackets
    it."""
    try:
        if ip_address(value).version == 4:
            return
    except ValueError:
        if _hostname.fullmatch(value):
            return
    raise ValidationError(_("Enter an IPv4 address or a host name, without a scheme, port or path"))


def validate_login(value):
    """A user name that goes safely into a libvirt connection URI and an ssh
    command line. Empty is allowed (TCP falls back to the server's own
    authentication, the socket transport ignores the login); otherwise only
    letters, digits, ".", "_" and "-", and never a leading "-" (an ssh
    option)."""
    if value and not _login.fullmatch(value):
        raise ValidationError(
            _("The login may contain only letters, digits, '.', '_' and '-', and may not start with '-'")
        )


def validate_name(value):
    if not _name.fullmatch(value):
        raise ValidationError(_("The name must not contain any special characters"))


def validate_migration_address(value):
    """An IP address (no IPv6 scope) or a host name: no scheme, port or brackets."""
    try:
        if not getattr(ip_address(value), "scope_id", None):
            return
    except ValueError:
        if _hostname.fullmatch(value):
            return
    raise ValidationError(_("Enter an IP address or a host name, without a scheme or port"))


def validate_gstfsd_key(value):
    """The key gstfsd on the host signs with: GSTFSD_KEY in its
    /etc/default/webvirt-gstfsd, 64 lowercase hexadecimal characters."""
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValidationError(_("Enter the 64 hexadecimal characters of GSTFSD_KEY in the host's /etc/default/webvirt-gstfsd"))
