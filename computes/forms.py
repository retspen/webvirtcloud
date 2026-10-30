from django import forms
from django.utils.translation import gettext_lazy as _
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS

from computes.models import Compute

from .validators import validate_hostname


class KeepSecretsMixin:
    """The form never shows the stored password or gstfsd key: left empty on
    an edit, they stay as they are."""

    def clean_password(self):
        return self.cleaned_data["password"] or self.instance.password

    def clean_gstfsd_key(self):
        return self.cleaned_data["gstfsd_key"] or self.instance.gstfsd_key


SECRET_WIDGETS = {"password": forms.PasswordInput(), "gstfsd_key": forms.PasswordInput()}


class TcpComputeForm(KeepSecretsMixin, forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TCP)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        fields = "__all__"


class SshComputeForm(KeepSecretsMixin, forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname], label=_("FQDN/IP"))
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SSH)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        exclude = ["password"]


class TlsComputeForm(KeepSecretsMixin, forms.ModelForm):
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TLS)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        fields = "__all__"


class SocketComputeForm(KeepSecretsMixin, forms.ModelForm):
    hostname = forms.CharField(widget=forms.HiddenInput, initial="localhost")
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SOCKET)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        fields = ["name", "details", "hostname", "type", "migration_address", "gstfsd_key"]
