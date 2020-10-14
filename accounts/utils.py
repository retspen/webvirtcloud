import base64
import binascii
import struct

from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice


def get_user_totp_device(user):
    devices = devices_for_user(user)
    for device in devices:
        if isinstance(device, TOTPDevice):
            return device


def validate_ssh_key(key):
    array = key.encode().split()
    # Each rsa-ssh key has 3 different strings in it, first one being
    # typeofkey second one being keystring third one being username .
    if len(array) != 3:
        return False
    typeofkey = array[0]
    string = array[1]
    username = array[2]
    # must have only valid rsa-ssh key characters ie binascii characters
    try:
        data = base64.decodestring(string)
    except binascii.Error:
        return False
    # unpack the contents of data, from data[:4] , property of ssh key .
    try:
        str_len = struct.unpack('>I', data[:4])[0]
    except struct.error:
        return False
    # data[4:str_len] must have string which matches with the typeofkey, another ssh key property.
    if data[4:4 + str_len] == typeofkey:
        return True
    else:
        return False
