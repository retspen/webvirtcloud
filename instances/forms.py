import re

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from webvirtcloud.settings import QEMU_CONSOLE_LISTENER_ADDRESSES, QEMU_KEYMAPS

from .models import CreateInstance, Flavor
from .utils import nic_macs


class FlavorForm(forms.ModelForm):
    # the units the create form fills in from a flavor
    memory = forms.IntegerField(label=_("Memory (MiB)"), min_value=1)
    vcpu = forms.IntegerField(label=_("vCPUs"), min_value=1)
    disk = forms.IntegerField(label=_("Disk (GiB)"), min_value=1)

    class Meta:
        model = Flavor
        fields = "__all__"


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
        super(ConsoleForm, self).__init__(*args, **kwargs)
        types = [("vnc", "VNC")]
        if settings.SERIAL_CONSOLE_ENABLED:
            types.append(("pty", _("Serial (xterm; the guest needs a getty on ttyS0)")))
        self.fields["console_type"].choices = types
        # the VNC settings are shown and saved while the console is VNC; a
        # switch to Serial ignores them
        if "pty" in (instance.config_console_type, self.data.get("console_type")):
            del self.fields["password_action"], self.fields["password"]
            return
        keymap_choices = [("auto", _("Auto"))] + list((c, c) for c in QEMU_KEYMAPS)
        # Only administrators choose the listen address: beyond localhost the
        # console is reachable from the network. A disabled field ignores
        # posted values.
        listeners = list(QEMU_CONSOLE_LISTENER_ADDRESSES)
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
        action = data.get("password_action")
        if action == "set":
            password = data.get("password", "")
            if not password:
                self.add_error("password", _("Enter the new password."))
            # VNC uses 8 bytes; libvirt refuses a longer password
            elif len(password.encode()) > 8:
                self.add_error("password", _("A VNC password takes at most 8 bytes."))
        # A console that listens beyond localhost (set by an administrator)
        # keeps its password unless an administrator removes it.
        if action == "none" and not self.is_superuser and not self.instance.proxy.console_listens_locally():
            self.add_error(
                "password_action",
                _("The console listens beyond localhost; only an administrator can remove its password."),
            )
        return data


class NewVMForm(forms.ModelForm):
    # name = forms.CharField(error_messages={'required': _('No Virtual Machine name has been entered')}, max_length=64)
    # firmware = forms.CharField(max_length=50, required=False)
    # vcpu = forms.IntegerField(error_messages={'required': _('No VCPU has been entered')})
    # disk = forms.IntegerField(required=False)
    # memory = forms.IntegerField(error_messages={'required': _('No RAM size has been entered')})
    # networks = forms.CharField(error_messages={'required': _('No Network pool has been choosen')})
    # nwfilter = forms.CharField(required=False)
    # storage = forms.CharField(max_length=20, required=False)
    # template = forms.CharField(required=False)
    # images = forms.CharField(required=False)
    # cache_mode = forms.CharField(error_messages={'required': _('Please select HDD cache mode')})
    # hdd_size = forms.IntegerField(required=False)
    # meta_prealloc = forms.BooleanField(required=False)
    # virtio = forms.BooleanField(required=False)
    # qemu_ga = forms.BooleanField(required=False)
    # mac = forms.CharField(required=False)
    # graphics = forms.CharField(error_messages={'required': _('Please select a graphics type')})
    # video = forms.CharField(error_messages={'required': _('Please select a video driver')})
    # listener_addr = forms.ChoiceField(required=True, widget=forms.RadioSelect, choices=QEMU_CONSOLE_LISTENER_ADDRESSES)
    class Meta:
        model = CreateInstance
        fields = "__all__"
        exclude = ["compute"]

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
