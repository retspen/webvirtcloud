import re
from django import forms
from django.utils.translation import ugettext_lazy as _
from computes.models import Compute
from vrtManager.connection import CONN_TCP, CONN_SSH, CONN_TLS, CONN_SOCKET
from .validators import validate_hostname


class TcpComputeForm(forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TCP)

    class Meta:
        model = Compute
        fields = '__all__'


class SshComputeForm(forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname], label=_("FQDN/IP"))
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SSH)

    class Meta:
        model = Compute
        exclude = ['password']


class TlsComputeForm(forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TLS)

    class Meta:
        model = Compute
        fields = '__all__'


class SocketComputeForm(forms.ModelForm):
    hostname = forms.CharField(widget=forms.HiddenInput, initial='localhost')
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SOCKET)

    class Meta:
        model = Compute
        fields = ['name', 'details', 'hostname', 'type']


class ComputeEditHostForm(forms.Form):
    host_id = forms.CharField()
    name = forms.CharField(error_messages={'required': _('No hostname has been entered')}, max_length=64)
    hostname = forms.CharField(error_messages={'required': _('No IP / Domain name has been entered')}, max_length=100)
    login = forms.CharField(error_messages={'required': _('No login has been entered')}, max_length=100)
    password = forms.CharField(max_length=100)
    details = forms.CharField(max_length=50, required=False)

    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', name)
        if have_symbol:
            raise forms.ValidationError(
                _('The name of the host must not contain any special characters'))
        elif len(name) > 20:
            raise forms.ValidationError(
                _('The name of the host must not exceed 20 characters'))
        return name

    def clean_hostname(self):
        hostname = self.cleaned_data['hostname']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', hostname)
        wrong_ip = re.match('^0.|^255.', hostname)
        if have_symbol:
            raise forms.ValidationError(
                _('Hostname must contain only numbers, or the domain name separated by "."'))
        elif wrong_ip:
            raise forms.ValidationError(_('Wrong IP address'))
        return hostname
