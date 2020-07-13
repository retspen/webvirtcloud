import re

from django import forms
from django.utils.translation import ugettext_lazy as _

from appsettings.models import AppSettings
from webvirtcloud.settings import QEMU_CONSOLE_LISTEN_ADDRESSES, QEMU_KEYMAPS

from .models import Flavor


class FlavorForm(forms.ModelForm):
    class Meta:
        model = Flavor
        fields = '__all__'


class ConsoleForm(forms.Form):
    type = forms.ChoiceField()
    listen_on = forms.ChoiceField()
    generate_password = forms.BooleanField(required=False)
    clear_password = forms.BooleanField(required=False)
    password = forms.CharField(widget=forms.PasswordInput(render_value=True), required=False)
    clear_keymap = forms.BooleanField(required=False)
    keymap = forms.ChoiceField(required=False)

    def __init__(self, *args, **kwargs):
        super(ConsoleForm, self).__init__(*args, **kwargs)
        type_choices = ((c, c) for c in AppSettings.objects.get(key="QEMU_CONSOLE_DEFAULT_TYPE").choices_as_list())
        keymap_choices = [('auto', 'Auto')] + list((c, c) for c in QEMU_KEYMAPS)
        self.fields['type'] = forms.ChoiceField(choices=type_choices)
        self.fields['listen_on'] = forms.ChoiceField(choices=QEMU_CONSOLE_LISTEN_ADDRESSES)
        self.fields['keymap'] = forms.ChoiceField(choices=keymap_choices)


class NewVMForm(forms.Form):
    name = forms.CharField(error_messages={'required': _('No Virtual Machine name has been entered')}, max_length=64)
    firmware = forms.CharField(max_length=50, required=False)
    vcpu = forms.IntegerField(error_messages={'required': _('No VCPU has been entered')})
    vcpu_mode = forms.CharField(max_length=20, required=False)
    disk = forms.IntegerField(required=False)
    memory = forms.IntegerField(error_messages={'required': _('No RAM size has been entered')})
    networks = forms.CharField(error_messages={'required': _('No Network pool has been choosen')})
    nwfilter = forms.CharField(required=False)
    storage = forms.CharField(max_length=20, required=False)
    template = forms.CharField(required=False)
    images = forms.CharField(required=False)
    cache_mode = forms.CharField(error_messages={'required': _('Please select HDD cache mode')})
    hdd_size = forms.IntegerField(required=False)
    meta_prealloc = forms.BooleanField(required=False)
    virtio = forms.BooleanField(required=False)
    qemu_ga = forms.BooleanField(required=False)
    mac = forms.CharField(required=False)
    console_pass = forms.CharField(required=False, empty_value="", widget=forms.PasswordInput())
    graphics = forms.CharField(error_messages={'required': _('Please select a graphics type')})
    video = forms.CharField(error_messages={'required': _('Please select a video driver')})
    listener_addr = forms.ChoiceField(required=True, widget=forms.RadioSelect, choices=QEMU_CONSOLE_LISTEN_ADDRESSES)

    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('^[a-zA-Z0-9._-]+$', name)
        if not have_symbol:
            raise forms.ValidationError(_('The name of the virtual machine must not contain any special characters'))
        elif len(name) > 64:
            raise forms.ValidationError(_('The name of the virtual machine must not exceed 20 characters'))
        return name
