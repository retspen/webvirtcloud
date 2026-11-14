import ipaddress
import re

from django import forms
from django.utils.translation import gettext_lazy as _


class AddInterface(forms.Form):
    name = forms.CharField(max_length=15, required=True)
    itype = forms.ChoiceField(
        required=True, choices=(("bridge", "bridge"), ("ethernet", "ethernet"))
    )
    start_mode = forms.ChoiceField(
        required=True,
        choices=(("none", "none"), ("onboot", "onboot"), ("hotplug", "hotplug")),
    )
    # a bridge's member; an ethernet interface configures the device in name
    netdev = forms.CharField(max_length=15, required=False)
    ipv4_type = forms.ChoiceField(
        required=True,
        choices=(("dhcp", "dhcp"), ("static", "static"), ("none", "none")),
    )
    # room for a dotted netmask: 192.0.2.10/255.255.255.0
    ipv4_addr = forms.CharField(max_length=31, required=False)
    ipv4_gw = forms.CharField(max_length=15, required=False)
    ipv6_type = forms.ChoiceField(
        required=True,
        choices=(("dhcp", "dhcp"), ("static", "static"), ("none", "none")),
    )
    ipv6_addr = forms.CharField(max_length=100, required=False)
    ipv6_gw = forms.CharField(max_length=100, required=False)
    stp = forms.ChoiceField(required=False, choices=(("on", "on"), ("off", "off")))
    delay = forms.IntegerField(required=False, min_value=0)

    def __init__(self, *args, netdevs=(), members=(), defined=(), **kwargs):
        # The host's network devices. members: those a bridge can take
        # (wvmInterfaces.get_member_candidates); an ethernet interface
        # configures one of them too. The interfaces the host defines:
        # defining one again would replace its configuration.
        super().__init__(*args, **kwargs)
        self.netdevs = set(netdevs)
        self.members = set(members)
        self.defined = set(defined)

    def clean_ipv4_addr(self):
        ipv4_addr = self.cleaned_data["ipv4_addr"]
        if not ipv4_addr:
            return ipv4_addr
        try:
            # Always address/prefix, as the interface XML needs both
            return str(ipaddress.IPv4Interface(ipv4_addr))
        except ValueError:
            raise forms.ValidationError(_("The IPv4 address is not valid (e.g. 192.0.2.10/24)"))

    def clean_ipv4_gw(self):
        ipv4_gw = self.cleaned_data["ipv4_gw"]
        if not ipv4_gw:
            return ipv4_gw
        try:
            return str(ipaddress.IPv4Address(ipv4_gw))
        except ValueError:
            raise forms.ValidationError(_("The IPv4 gateway is not valid"))

    # libvirt's interface schema has no IPv6 scope id (fe80::1%eth0)
    def clean_ipv6_addr(self):
        ipv6_addr = self.cleaned_data["ipv6_addr"]
        if not ipv6_addr:
            return ipv6_addr
        try:
            address = ipaddress.IPv6Interface(ipv6_addr)
        except ValueError:
            address = None
        if address is None or address.scope_id is not None:
            raise forms.ValidationError(_("The IPv6 address is not valid (e.g. 2001:db8::10/64)"))
        # Always address/prefix, as the interface XML needs both
        return str(address)

    def clean_ipv6_gw(self):
        ipv6_gw = self.cleaned_data["ipv6_gw"]
        if not ipv6_gw:
            return ipv6_gw
        try:
            gateway = ipaddress.IPv6Address(ipv6_gw)
        except ValueError:
            gateway = None
        if gateway is None or gateway.scope_id is not None:
            raise forms.ValidationError(_("The IPv6 gateway is not valid"))
        return str(gateway)

    def clean_name(self):
        # A Linux interface name: up to 15 characters, no spaces or slashes
        name = self.cleaned_data["name"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", name) or name in (".", ".."):
            raise forms.ValidationError(
                _("The interface name may have up to 15 letters, digits and . _ -")
            )
        if name in self.defined:
            raise forms.ValidationError(_("The host already defines interface %(name)s") % {"name": name})
        return name

    def clean_netdev(self):
        netdev = self.cleaned_data["netdev"]
        if not netdev:
            return netdev
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", netdev) or netdev in (".", ".."):
            raise forms.ValidationError(
                _("The device name may have up to 15 letters, digits and . _ -")
            )
        return netdev

    def clean(self):
        cleaned = super().clean()
        for family in ("ipv4", "ipv6"):
            addr = f"{family}_addr"
            if cleaned.get(f"{family}_type") == "static" and not cleaned.get(addr) and addr not in self.errors:
                self.add_error(addr, _("A static configuration needs an address"))
        name, netdev = cleaned.get("name"), cleaned.get("netdev")
        if cleaned.get("itype") == "bridge":
            if not cleaned.get("stp") and "stp" not in self.errors:
                self.add_error("stp", _("A bridge needs STP on or off"))
            if cleaned.get("delay") is None and "delay" not in self.errors:
                self.add_error("delay", _("A bridge needs a forward delay"))
            if not netdev and "netdev" not in self.errors:
                self.add_error("netdev", _("A bridge needs a device"))
            elif netdev and netdev not in self.netdevs:
                self.add_error("netdev", _("The device is not on this host"))
            elif netdev and netdev not in self.members:
                self.add_error("netdev", _("The device is a bridge, bond or VLAN, a member of one, or a VM's"))
            elif netdev and netdev == name:
                self.add_error("netdev", _("A bridge cannot contain itself"))
        elif cleaned.get("itype") == "ethernet" and name and name not in self.members:
            self.add_error("name", _("An ethernet interface configures a device of this host in no bridge, bond or VLAN"))
        return cleaned
