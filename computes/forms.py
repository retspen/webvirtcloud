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
        widgets = {'password': forms.PasswordInput()}
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
        widgets = {'password': forms.PasswordInput()}
        fields = '__all__'


class SocketComputeForm(forms.ModelForm):
    hostname = forms.CharField(widget=forms.HiddenInput, initial='localhost')
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SOCKET)

    class Meta:
        model = Compute
        fields = ['name', 'details', 'hostname', 'type']
