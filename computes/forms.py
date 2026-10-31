from django import forms
from django.utils.translation import gettext_lazy as _
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS

from computes.models import Compute

from .validators import validate_hostname


class KeepSecretsMixin:
    """The form never shows the stored password or gstfsd key: left empty on
    an edit, they stay as they are."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("password", "gstfsd_key"):
            if name in self.fields and getattr(self.instance, name):
                self.fields[name].widget.attrs["placeholder"] = _("Stored, leave empty to keep")

    def clean_password(self):
        return self.cleaned_data["password"] or self.instance.password

    def clean_gstfsd_key(self):
        return self.cleaned_data["gstfsd_key"] or self.instance.gstfsd_key


SECRET_WIDGETS = {"password": forms.PasswordInput(), "gstfsd_key": forms.PasswordInput()}
DETAILS = {"details": _("Description")}
DETAILS_HELP = {"details": _("Shown on the hosts list")}
SASL_LABELS = {"login": _("SASL login"), "password": _("SASL password")} | DETAILS


class TcpComputeForm(KeepSecretsMixin, forms.ModelForm):
    kind = "TCP"
    about = _("libvirt over TCP, with a SASL login")
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TCP)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = SASL_LABELS
        help_texts = DETAILS_HELP
        fields = "__all__"


class SshComputeForm(KeepSecretsMixin, forms.ModelForm):
    kind = "SSH"
    about = _("libvirt over SSH, with the panel's SSH key")
    hostname = forms.CharField(validators=[validate_hostname], label=_("FQDN/IP"))
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SSH)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = {"login": _("SSH user")} | DETAILS
        help_texts = DETAILS_HELP
        exclude = ["password"]


class TlsComputeForm(KeepSecretsMixin, forms.ModelForm):
    kind = "TLS"
    about = _("libvirt over TLS, with certificates")
    hostname = forms.CharField(validators=[validate_hostname])
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_TLS)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = SASL_LABELS
        help_texts = DETAILS_HELP
        fields = "__all__"


class SocketComputeForm(KeepSecretsMixin, forms.ModelForm):
    kind = _("Local")
    about = _("the libvirt of the host the panel runs on, by its socket")
    hostname = forms.CharField(widget=forms.HiddenInput, initial="localhost")
    type = forms.IntegerField(widget=forms.HiddenInput, initial=CONN_SOCKET)

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = DETAILS
        help_texts = DETAILS_HELP
        fields = ["name", "details", "hostname", "type", "migration_address", "gstfsd_key"]
