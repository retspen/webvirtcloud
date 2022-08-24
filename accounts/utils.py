import base64
import binascii
import struct

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice


def get_user_totp_device(user):
    devices = devices_for_user(user)
    for device in devices:
        if isinstance(device, TOTPDevice):
            return device

    device = user.totpdevice_set.create()
    return device


def validate_ssh_key(key):
    array = key.encode().split()
    # Each rsa-ssh key has 3 different strings in it, first one being
    # typeofkey second one being keystring third one being username .
    if len(array) != 3:
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
            },
        ),
        fail_silently=False,
    )
