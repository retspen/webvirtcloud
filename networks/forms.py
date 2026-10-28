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
    """A new network of the host. networks: the host's networks
    (get_networks_info), whose names it may not take nor overlap their
    subnets. NAT and routed networks need an IPv4 subnet; an isolated one
    may have none; a bridge or macvtap network takes its addresses from the
    outside network, and needs the host's bridge or interface."""

    MODES = ("nat", "route", "none", "bridge", "macvtap")

    name = forms.CharField(
        error_messages={"required": _("No pool name has been entered")},
        max_length=20
    )
    subnet = forms.CharField(label=_("IPv4 subnet"), max_length=20, required=False)
    subnet6 = forms.CharField(label=_("IPv6 subnet"), max_length=42, required=False)
    forward = forms.ChoiceField(choices=[(mode, mode) for mode in MODES])
    dhcp4 = forms.BooleanField(required=False)
    enable_ipv6 = forms.BooleanField(required=False)
    dhcp6 = forms.BooleanField(required=False)
    bridge_name = forms.CharField(label=_("Bridge or interface"), max_length=20, required=False)
    openvswitch = forms.BooleanField(required=False)

    def __init__(self, *args, networks=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.networks = networks

    def clean_name(self):
        name = self.cleaned_data["name"]
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", name):
            raise forms.ValidationError(
                _("The pool name must not contain any special characters")
            )
        if any(net["name"] == name for net in self.networks):
            raise forms.ValidationError(_("This host has a network of that name"), code="taken")
        return name

    def clean_subnet(self):
        return checked_subnet(self.cleaned_data["subnet"], 4)

    def clean_subnet6(self):
        return checked_subnet(self.cleaned_data["subnet6"], 6)

    def clean_bridge_name(self):
        bridge_name = self.cleaned_data["bridge_name"]
        if bridge_name and not re.fullmatch(r"[a-zA-Z0-9._:-]+", bridge_name):
            raise forms.ValidationError(
                _("The pool bridge name must not contain any special characters")
            )
        return bridge_name

    def clean(self):
        data = super().clean()
        mode = data.get("forward")
        if mode in ("bridge", "macvtap"):
            # the outside network gives the addresses: none of libvirt's
            data.update(subnet="", subnet6="", dhcp4=False, dhcp6=False)
            if not data.get("bridge_name") and "bridge_name" not in self.errors:
                self.add_error("bridge_name", _("This field is required."))
        else:
            data["bridge_name"] = ""
            if mode in ("nat", "route") and not data.get("subnet") and "subnet" not in self.errors:
                self.add_error("subnet", _("This field is required."))
            if not data.get("enable_ipv6"):
                data["subnet6"] = ""
            elif not data.get("subnet6") and "subnet6" not in self.errors:
                self.add_error("subnet6", _("This field is required."))
        if mode != "bridge":
            data["openvswitch"] = False
        for field in ("subnet", "subnet6"):
            if data.get(field) and field not in self.errors:
                subnet = ipaddress.ip_network(data[field], strict=False)
                for net in self.networks:
                    taken = next((ip["subnet"] for ip in net["ips"]
                                  if ip["subnet"] and ip["subnet"].version == subnet.version and ip["subnet"].overlaps(subnet)), None)
                    if taken:
                        self.add_error(field, _("Network %(net)s has %(subnet)s") % {"net": net["name"], "subnet": taken})
                        break
        return data
