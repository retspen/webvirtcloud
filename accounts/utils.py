import base64
import binascii
import struct
from decimal import Decimal

import segno
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.signing import TimestampSigner
from django.db import transaction
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice


def get_existing_totp_device(user):
    """The user's confirmed TOTP device, or None. Unlike get_user_totp_device
    it never creates one, so an unauthenticated caller cannot turn a
    password-only account into an OTP-required one."""
    for device in devices_for_user(user, confirmed=True):
        if isinstance(device, TOTPDevice):
            return device
    return None


def get_user_totp_device(user):
    """The user's TOTP device, made if they have none. The user's row is
    locked meanwhile: two requests at once (a double click) make one device,
    not two that both log in."""
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        for device in devices_for_user(user):
            if isinstance(device, TOTPDevice):
                return device
        return user.totpdevice_set.create()


def validate_ssh_key(key):
    # An OpenSSH public key is a type, a key and an optional comment, which may hold spaces
    array = key.strip().encode().split(maxsplit=2)
    if len(array) < 2:
        return False
    typeofkey = array[0]
    string = array[1]

    # must have only valid rsa-ssh key characters ie binascii characters
    try:
        data = base64.decodebytes(string)
    except binascii.Error:
        return False
    # unpack the contents of data, from data[:4] , property of ssh key .
    try:
        str_len = struct.unpack(">I", data[:4])[0]
    except struct.error:
        return False
    # data[4:str_len] must have string which matches with the typeofkey, another ssh key property.
    if data[4 : 4 + str_len] != typeofkey:
        return False
    return True


# the link a mail carries to its user's OTP QR code: the mail holds no secret
OTP_LINK = TimestampSigner(salt="accounts.otp_qr")
OTP_LINK_MAX_AGE = 3600


def send_email_with_otp(request, user):
    """Mail the user a link to the page of their OTP QR code, good for
    OTP_LINK_MAX_AGE: the QR code's secret is never in a mailbox. The token
    is the URL's fragment, which no request carries: it is in no access log."""
    url = request.build_absolute_uri(reverse("accounts:otp_qr")) + "#" + OTP_LINK.sign(str(user.pk))
    send_mail(
        _("OTP QR Code"),
        _("Open this link within an hour to see the OTP QR code of account '%(user)s':\n\n%(url)s")
        % {"user": user, "url": url},
        None,
        [user.email],
        fail_silently=False,
    )


def otp_qr_svg(device):
    """The device's QR code as inline SVG: 1.8 mm modules, error correction M, a 4-module border."""
    qr = segno.make(device.config_url, error="m", mode="byte", encoding="utf-8", micro=False)
    return mark_safe(qr.svg_inline(scale=Decimal("1.8"), unit="mm", border=4, dark="black", light="white"))
