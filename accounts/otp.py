"""The login form used when OTP_ENABLED.

django-otp's ``OTPAuthenticationForm`` requires every user to present a token
and, since 1.6, to name the device explicitly, so the single-field login page
cannot satisfy it and a user who never enrolled is locked out. This form makes
OTP per user: a user with a confirmed TOTP device must enter a valid code, one
without a device logs in with the password alone. The device is chosen by the
server, so the page needs only the token field and a posted device id (which
django-otp does not check for confirmed status or ownership-by-type) is
ignored.
"""

from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from django_otp.forms import OTPAuthenticationForm
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.forms import BoundedUsernameMixin


class SingleDeviceOTPForm(BoundedUsernameMixin, OTPAuthenticationForm):
    # the errors this form can give, here so that the panel's catalogs translate them
    otp_error_messages = dict(
        OTPAuthenticationForm.otp_error_messages,
        token_required=_("Please enter your OTP token."),
        invalid_token=_("Invalid token. Please make sure you have entered it correctly."),
        n_failed_attempts=ngettext_lazy(
            "Verification temporarily disabled because of %(failure_count)d failed attempt, please try again soon.",
            "Verification temporarily disabled because of %(failure_count)d failed attempts, please try again soon.",
            "failure_count",
        ),
        verification_not_allowed=_("Verification of the token is currently disabled"),
    )

    def _confirmed_totp(self, user, for_verify=False):
        """The user's oldest confirmed TOTP device, or None. With for_verify
        the row is locked (select_for_update) so the token's replay and
        throttling counters cannot race; call it only inside clean_otp's
        transaction."""
        devices = TOTPDevice.objects.filter(user=user, confirmed=True)
        if for_verify:
            devices = devices.select_for_update()
        return devices.order_by("id").first()

    def _chosen_device(self, user):
        # Ignore a posted otp_device: it is verified within clean_otp's
        # transaction, where the lock belongs.
        return self._confirmed_totp(user, for_verify=True)

    def clean_otp(self, user):
        if user is not None and self._confirmed_totp(user) is None:
            return  # no confirmed device: the password is the only factor
        try:
            return super().clean_otp(user)
        except ValidationError:
            # a wrong code is a failed login: counted by django-axes and logged
            user_login_failed.send(sender=__name__, credentials={"username": user.get_username()}, request=self.request)
            raise
