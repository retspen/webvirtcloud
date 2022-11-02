import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

have_symbol = re.compile("[^a-zA-Z0-9._-]+")
wrong_ip = re.compile("^0.|^255.")
wrong_name = re.compile("[^a-zA-Z0-9._-]+")


def validate_hostname(value):
    sym = have_symbol.match(value)
    wip = wrong_ip.match(value)

    if sym:
        raise ValidationError(
            _('Hostname must contain only numbers, or the domain name separated by "."')
        )
    elif wip:
        raise ValidationError(_("Wrong IP address"))


def validate_name(value):
    have_symbol = wrong_name.match("[^a-zA-Z0-9._-]+")
    if have_symbol:
        raise ValidationError(_("The hostname must not contain any special characters"))
