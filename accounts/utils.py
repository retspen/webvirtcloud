import base64
import binascii
import struct
from decimal import Decimal

import segno
from django.core.mail import send_mail
from django.template.loader import render_to_string
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
    devices = devices_for_user(user)
    for device in devices:
        if isinstance(device, TOTPDevice):
            return device

    device = user.totpdevice_set.create()
    return device


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


def send_email_with_otp(user, device):
    # An inline SVG (1.8 mm modules) and, for mail clients that show no SVG,
    # a PNG (12 px modules); error correction M, 4-module border.
    qr = segno.make(device.config_url, error="m", mode="byte", encoding="utf-8", micro=False)
    style = {"border": 4, "dark": "black", "light": "white"}
    send_mail(
        _("OTP QR Code"),
        _("Please view HTML version of this message."),
        None,
        [user.email],
        html_message=render_to_string(
            "accounts/email/otp.html",
            {
                "totp_url": device.config_url,
                "user": user,
                "qr_svg": mark_safe(qr.svg_inline(scale=Decimal("1.8"), unit="mm", **style)),
                "qr_png": qr.png_data_uri(scale=12, **style),
            },
        ),
        fail_silently=False,
    )
