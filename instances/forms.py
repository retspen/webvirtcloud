import re

from django import forms
from django.conf import settings
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext_lazy as _

from .models import Flavor
from .utils import nic_macs


class FlavorForm(forms.ModelForm):
    # the units the create form fills in from a flavor
    memory = forms.IntegerField(label=_("Memory (MiB)"), min_value=1)
    vcpu = forms.IntegerField(label=_("vCPUs"), min_value=1)
    disk = forms.IntegerField(label=_("Disk (GiB)"), min_value=1)

    class Meta:
        model = Flavor
        fields = "__all__"


def console_seen(console_type, listener, keymap, passwd):
    """The fingerprint of the console settings a page shows, which it sends
    back: a page opened before another change would undo it."""
    return salted_hmac("instances.console_seen", repr((console_type, listener, keymap, passwd)), algorithm="sha256").hexdigest()


class ConsoleForm(forms.Form):
    console_type = forms.ChoiceField(
        label=_("Console type"), required=False, widget=forms.Select(attrs={"class": "form-select"})
    )
    password_action = forms.ChoiceField(
        label=_("Password"),
        choices=[
            ("keep", _("Keep the password")),
            ("generate", _("Generate a new one")),
            ("set", _("Set a new one")),
            ("none", _("No password")),
        ],
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )
    password = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        required=False,
        strip=False,
    )
    seen = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, instance, is_superuser, **kwargs):
        # the VM's settings as the initial values: a save changes only the fields edited
        self.instance = instance
        self.is_superuser = is_superuser
        listener = instance.config_console_listener_address
        kwargs["initial"] = {
            "console_type": instance.config_console_type,
            "listen_on": listener,
            "password_action": "keep",
            "keymap": instance.config_console_keymap or "auto",
        }
        kwargs["initial"]["seen"] = console_seen(*(kwargs["initial"][k] for k in ("console_type", "listen_on", "keymap")),
                                                 instance.config_console_passwd)
        super(ConsoleForm, self).__init__(*args, **kwargs)
        types = [("vnc", "VNC")]
        if settings.SERIAL_CONSOLE_ENABLED:
            types.append(("pty", _("Serial (xterm; the guest needs a getty on ttyS0)")))
        # a type the panel does not create (SPICE) is offered, so a save keeps it
        if instance.config_console_type not in (None, "pty", "vnc"):
            types.append((instance.config_console_type, instance.config_console_type.upper()))
        self.fields["console_type"].choices = types
        # the VNC settings are shown and saved while the console is VNC; a
        # switch to Serial ignores them
        if "pty" in (instance.config_console_type, self.data.get("console_type")):
            del self.fields["password_action"], self.fields["password"]
            return
        keymap_choices = [("auto", _("Auto"))] + list((c, c) for c in settings.QEMU_KEYMAPS)
        # Only administrators choose the listen address: beyond localhost the
        # console is reachable from the network. A disabled field ignores
        # posted values.
        listeners = list(settings.QEMU_CONSOLE_LISTENER_ADDRESSES)
        # an address set elsewhere (the XML editor) is offered, so a save keeps it
        if listener and listener not in dict(listeners):
            listeners.append((listener, listener))
        self.fields["listen_on"] = forms.ChoiceField(
            label=_("Listen on"),
            choices=listeners,
            disabled=not is_superuser,
            required=is_superuser,
            widget=forms.Select(attrs={"class": "form-select"}),
        )
        self.fields["keymap"] = forms.ChoiceField(
            label=_("Keymap"), choices=keymap_choices, widget=forms.Select(attrs={"class": "form-select"})
        )

    def clean(self):
        data = super().clean()
        if data.get("seen") != self.initial["seen"]:
            raise forms.ValidationError(_("The console settings were changed meanwhile; check them and save again."))
        action = data.get("password_action")
        if action == "set":
            password = data.get("password", "")
            if not password:
                self.add_error("password", _("Enter the new password."))
            # VNC takes 8 bytes, and the browser console sends only ASCII as typed
            elif (data.get("console_type") or self.initial["console_type"]) == "vnc" and (
                    len(password) > 8 or not all(" " <= c <= "~" for c in password)):
                self.add_error("password", _("A VNC password takes up to 8 letters, digits or symbols, without accents."))
            elif not password.isprintable():  # a SPICE password
                self.add_error("password", _("A password takes no line breaks or other control characters."))
        # refused before anything is saved; a new console type gets an address listener
        if ("listen_on" in self.changed_data and data.get("console_type") in ("", self.initial["console_type"])
                and self.instance.proxy.get_console_listen_type(config=True) in ("network", "socket", "none")):
            self.add_error("listen_on", _("The console listens on no address (on a network, a socket or nowhere); "
                                          "change it in the XML editor"))
        # A console that listens beyond localhost (set by an administrator)
        # keeps its password unless an administrator removes it.
        if action == "none" and not self.is_superuser and not self.instance.proxy.console_listens_locally():
            self.add_error(
                "password_action",
                _("The console listens beyond localhost; only an administrator can remove its password."),
            )
        return data


class NewVMForm(forms.Form):
    """The new VM form (create_instance_w2.html); the API takes CreateInstanceSerializer."""

    name = forms.CharField(max_length=64)
    # empty: the machine's own, for an architecture with no firmware choice
    firmware = forms.CharField(max_length=64, required=False)
    # an emulated TPM 2.0, as Windows 11 needs
    tpm = forms.BooleanField(required=False)
    vcpu = forms.IntegerField(min_value=1)
    # a mode of libvirt's (host-model, host-passthrough, maximum) or a CPU model's name
    vcpu_mode = forms.CharField(max_length=64)
    disk = forms.IntegerField(required=False)
    memory = forms.IntegerField(min_value=1)
    networks = forms.CharField(max_length=256)
    nwfilter = forms.CharField(max_length=256, required=False)
    net_model = forms.CharField(max_length=256, required=False)
    storage = forms.CharField(max_length=256, required=False)
    template = forms.CharField(max_length=256, required=False)
    template_pool = forms.CharField(max_length=256, required=False)
    images = forms.CharField(max_length=256, required=False)  # existing volumes, each "pool/volume"
    cache_mode = forms.CharField(max_length=16)
    hdd_size = forms.IntegerField(min_value=1, required=False)
    meta_prealloc = forms.BooleanField(required=False)
    virtio = forms.BooleanField(required=False, initial=True)
    qemu_ga = forms.BooleanField(required=False)
    mac = forms.CharField(max_length=255, required=False)  # one per NIC, comma separated
    add_cdrom = forms.CharField(max_length=16)
    # a NoCloud seed on a CD-ROM: the hostname and the creating user's SSH keys
    cloud_init = forms.BooleanField(required=False)
    add_input = forms.CharField(max_length=16)
    video = forms.CharField(max_length=16)
    listener_addr = forms.ChoiceField(choices=settings.QEMU_CONSOLE_LISTENER_ADDRESSES)

    def clean_name(self):
        name = self.cleaned_data["name"]
        have_symbol = re.match("^[a-zA-Z0-9._-]+$", name)
        if not have_symbol:
            raise forms.ValidationError(
                _(
                    "The name of the virtual machine must not contain any special characters"
                )
            )
        return name

    def clean(self):
        # one MAC per NIC at most, each a MAC address, as the job checks
        cleaned = super().clean()
        try:
            nic_macs(cleaned.get("mac") or "", cleaned.get("networks") or "")
        except ValueError as err:
            self.add_error("mac", str(err))
        return cleaned
