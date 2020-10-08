from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice


def get_user_totp_device(user):
    devices = devices_for_user(user)
    for device in devices:
        if isinstance(device, TOTPDevice):
            return device
