import re

from appsettings.models import AppSettings
from django import forms
from django.utils.translation import gettext_lazy as _
from webvirtcloud.settings import QEMU_CONSOLE_LISTENER_ADDRESSES, QEMU_KEYMAPS

from .models import CreateInstance, Flavor


class FlavorForm(forms.ModelForm):
    class Meta:
        model = Flavor
        fields = "__all__"


class ConsoleForm(forms.Form):
    type = forms.ChoiceField(label=_("Type"))
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

    def __init__(self, *args, **kwargs):
        super(ConsoleForm, self).__init__(*args, **kwargs)
        type_choices = (
            (c, c)
            for c in AppSettings.objects.get(key="QEMU_CONSOLE_DEFAULT_TYPE").choices_as_list()
        )
        keymap_choices = [("auto", _("Auto"))] + list((c, c) for c in QEMU_KEYMAPS)
        self.fields["type"] = forms.ChoiceField(label=_("Type"), choices=type_choices)
        self.fields["listen_on"] = forms.ChoiceField(
            label=_("Listen on"),
            choices=QEMU_CONSOLE_LISTENER_ADDRESSES
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
    # console_pass = forms.CharField(required=False, empty_value="", widget=forms.PasswordInput())
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
