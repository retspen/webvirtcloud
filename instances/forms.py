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
    console_type = forms.ChoiceField(label=_("Console type"), required=False)
    listen_on = forms.ChoiceField(label=_("Listen on"))
    generate_password = forms.BooleanField(label=_("Generate password"), required=False)
    clear_password = forms.BooleanField(label=_("Clear password"), required=False)
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(render_value=True),
        required=False
    )
    clear_keymap = forms.BooleanField(label=_("Clear keymap"), required=False)
    keymap = forms.ChoiceField(label=_("Keymap"), required=False)

    def __init__(self, *args, instance, can_set_listener, **kwargs):
        # the VM's settings as the initial values: a save changes only the fields edited
        listener = instance.config_console_listener_address
        kwargs["initial"] = {
            "console_type": instance.console_type,
            "listen_on": listener,
            "password": instance.config_console_passwd,
            "keymap": instance.config_console_keymap or "auto",
        }
        super(ConsoleForm, self).__init__(*args, **kwargs)
        types = [("vnc", "VNC")]
        if settings.SERIAL_CONSOLE_ENABLED:
            types.append(("pty", _("Serial (xterm; the guest needs a getty on ttyS0)")))
        self.fields["console_type"].choices = types
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
            disabled=not can_set_listener,
            required=can_set_listener,
        )
        self.fields["keymap"] = forms.ChoiceField(label=_("Keymap"), choices=keymap_choices)


class NewVMForm(forms.ModelForm):
    # name = forms.CharField(error_messages={'required': _('No Virtual Machine name has been entered')}, max_length=64)
    # firmware = forms.CharField(max_length=50, required=False)
    # vcpu = forms.IntegerField(error_messages={'required': _('No VCPU has been entered')})
    # vcpu_mode = forms.CharField(max_length=20, required=False)
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
