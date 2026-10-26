"""The console token: the console view signs "host:uuid:user_id" for the VM
whose console it shows; the console daemons (novncd, socketiod) accept it for
120 s if that user may still open that VM's console. A bearer token: whoever
holds it within that time gets the console."""

from django.contrib.auth import get_user_model
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

from instances.models import Instance
from instances.utils import can_open_console

SIGNER = TimestampSigner(salt="console.novnc")
MAX_AGE = 120


def authorize(token):
    """The Instance the token opens and the user it was given to;
    PermissionError otherwise."""
    try:
        host, uuid, user_id = SIGNER.unsign(token, max_age=MAX_AGE).split(":")
        host, user_id = int(host), int(user_id)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        raise PermissionError("Invalid or expired console token")
    instance = Instance.objects.filter(compute_id=host, uuid=uuid).select_related("compute").first()
    user = get_user_model().objects.filter(id=user_id, is_active=True).first()
    if instance is None or user is None or not can_open_console(user, instance):
        raise PermissionError("No access to this console")
    return instance, user
