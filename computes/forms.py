from django import forms
from django.utils.translation import gettext_lazy as _
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS

from computes.models import Compute

from .validators import validate_hostname


class TcpComputeForm(forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TCP)

    class Meta:
        model = Compute
        widgets = {"password": forms.PasswordInput()}
        fields = "__all__"


class SshComputeForm(forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname], label=_("FQDN/IP"))
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SSH)

    class Meta:
        model = Compute
        exclude = ["password"]


class TlsComputeForm(forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TLS)

    class Meta:
        model = Compute
        widgets = {"password": forms.PasswordInput()}
        fields = "__all__"


class SocketComputeForm(forms.ModelForm):
    hostname = forms.CharField(widget=forms.HiddenInput, initial="localhost")
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SOCKET)

    class Meta:
        model = Compute
        fields = ["name", "details", "hostname", "type"]
