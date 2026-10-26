import ipaddress
import re

from django import forms
from django.utils.translation import gettext_lazy as _


def checked_subnet(subnet, version):
    """subnet, if it is empty or an IPv<version> network that has room for a
    gateway, a DHCP range and (IPv4) a broadcast address; else a field error."""
    if not subnet:
        return subnet
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        network = None
    if network is None or network.version != version:
        raise forms.ValidationError(_("%(subnet)s is not an IPv%(version)s subnet") % {"subnet": subnet, "version": version})
    if version == 4 and network.prefixlen > 30:
        raise forms.ValidationError(_("The IPv4 network prefix must be /30 or shorter"))
    if version == 6 and network.prefixlen != 64:
        raise forms.ValidationError(_("For libvirt, the IPv6 network prefix must be /64"))
    return subnet


class AddNetPool(forms.Form):
    name = forms.CharField(
        error_messages={"required": _("No pool name has been entered")},
        max_length=20
    )
    subnet = forms.CharField(
        error_messages={"required": _("No IPv4 subnet has been entered")},
        max_length=20,
        required=False,
    )
    subnet6 = forms.CharField(
        error_messages={"required": _("No IPv6 subnet has been entered")},
        max_length=42,
        required=False,
    )
    forward = forms.CharField(max_length=100)
    dhcp4 = forms.BooleanField(required=False)
    dhcp6 = forms.BooleanField(required=False)
    fixed = forms.BooleanField(required=False)
    bridge_name = forms.CharField(max_length=20, required=False)
    openvswitch = forms.BooleanField(required=False)

    def clean_name(self):
        name = self.cleaned_data["name"]
        have_symbol = re.match(r"^[a-zA-Z0-9\.\_\-]+$", name)
        if not have_symbol:
            raise forms.ValidationError(
                _("The pool name must not contain any special characters")
            )
        elif len(name) > 20:
            raise forms.ValidationError(
                _("The pool name must not exceed 20 characters")
            )
        return name

    def clean_subnet(self):
        return checked_subnet(self.cleaned_data["subnet"], 4)

    def clean(self):
        cleaned = super().clean()
        # one fixed address per address of the DHCP range
        subnet = cleaned.get("subnet")
        if cleaned.get("fixed") and subnet and ipaddress.ip_network(subnet, strict=False).prefixlen < 24:
            self.add_error("fixed", _("Fixed addresses need an IPv4 subnet of /24 or smaller"))
        return cleaned

    def clean_subnet6(self):
        return checked_subnet(self.cleaned_data["subnet6"], 6)

    def clean_bridge_name(self):
        bridge_name = self.cleaned_data["bridge_name"]
        if self.cleaned_data["forward"] in ["bridge", "macvtap"]:
            have_symbol = re.match(r"^[a-zA-Z0-9\.\_\:\-]+$", bridge_name)
            if not have_symbol:
                raise forms.ValidationError(
                    _("The pool bridge name must not contain any special characters")
                )
            elif len(bridge_name) > 20:
                raise forms.ValidationError(
                    _("The pool bridge name must not exceed 20 characters")
                )
            return bridge_name
