"""The console token: the console view signs "host:uuid:user_id:console type"
for the VM whose console it shows; the console daemons (novncd for vnc,
socketiod for pty) accept it for 120 s if that user may still open that VM's
console. A bearer token: whoever holds it within that time gets the console."""

from django import db
from django.contrib.auth import get_user_model
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

from instances.models import Instance
from instances.utils import can_open_console

SIGNER = TimestampSigner(salt="console.novnc")
MAX_AGE = 120
ACCESS_CHECK = 10  # seconds between checks that an open console's user may still use it


def sign(compute_id, uuid, user_id, console_type):
    return SIGNER.sign(f"{compute_id}:{uuid}:{user_id}:{console_type}")


def authorize(token, console_type):
    """The Instance the token opens and the user it was given to;
    PermissionError otherwise, also for a token of another console type."""
    try:
        host, uuid, user_id, signed_type = SIGNER.unsign(token, max_age=MAX_AGE).split(":")
        host, user_id = int(host), int(user_id)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        raise PermissionError("Invalid or expired console token")
    if signed_type != console_type:
        raise PermissionError(f"The token is for a {signed_type} console")
    instance = Instance.objects.filter(compute_id=host, uuid=uuid).select_related("compute").first()
    user = get_user_model().objects.filter(id=user_id, is_active=True).first()
    if instance is None or user is None or not can_open_console(user, instance):
        raise PermissionError("No access to this console")
    return instance, user


def may_still_open(user_id, instance):
    """The user still may open the console: an owner may have been removed or
    the user deactivated since the session started."""
    try:
        user = get_user_model().objects.filter(pk=user_id).first()
        return user is not None and can_open_console(user, instance)
    finally:
        db.connection.close()  # a session may last for days: no idle connection meanwhile
