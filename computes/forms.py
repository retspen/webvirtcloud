from django import forms
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS

from computes.models import TAG_LENGTH, TAG_NAME, Compute, Tag
from computes.utils import lock_ownership

from .validators import validate_hostname


class KeepSecretsMixin:
    """The form never shows the stored password or gstfsd key: left empty on
    an edit, they stay as they are."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.type = self.conn_type  # the form's own kind, never a posted one
        if "password" in self.fields:
            self.fields["password"].strip = False  # a SASL password may begin or end with a space
        for name in ("password", "gstfsd_key"):
            if name in self.fields and getattr(self.instance, name):
                self.fields[name].widget.attrs["placeholder"] = _("Stored, leave empty to keep")

    def clean_password(self):
        return self.cleaned_data["password"] or self.instance.password

    def clean_gstfsd_key(self):
        return self.cleaned_data["gstfsd_key"] or self.instance.gstfsd_key


class TagsWidget(forms.SelectMultiple):
    """The tags there are and those given, to choose from or add to (Tom Select)."""

    def __init__(self):
        # Tom Select's line for a new name typed, and for one that cannot be a tag (searchable_select.js)
        super().__init__(attrs={"data-tags": "", "data-add": _("Add tag %(tag)s"), "data-rule": _(
            "A new tag: letters a-z, digits, dots, dashes and underscores, beginning with a letter or digit; "
            "at most 12 characters")})

    def optgroups(self, name, value, attrs=None):
        self.choices = [(n, n) for n in sorted(set(Tag.objects.values_list("name", flat=True)) | set(value))]
        return super().optgroups(name, value, attrs)


class TagsField(forms.Field):
    """Tag names, each once and in lower case; the tags are made when saved (Tag.named).
    The form carries the names it showed: sent back unchanged, they are not set again,
    so a form shown before a tag was renamed or deleted does not undo that."""

    widget = TagsWidget
    hidden_widget = forms.MultipleHiddenInput

    def __init__(self, **kwargs):
        super().__init__(required=False, label=_("Tags"), show_hidden_initial=True, **kwargs)

    def to_python(self, value):
        names = [str(name).strip().lower() for name in value or ()]
        return list(dict.fromkeys(name for name in names if name))

    def has_changed(self, initial, data):
        return set(self.to_python(initial)) != set(self.to_python(data))

    def validate(self, value):
        existing = set(Tag.objects.filter(name__in=value).values_list("name", flat=True))
        for name in value:
            if name not in existing:  # a tag made before the limit can still be given
                TAG_LENGTH(name)
            TAG_NAME(name)


class TagsForm(forms.Form):
    tags = TagsField()


class ComputeTagsMixin:
    """The compute's tags on its form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tags"] = TagsField()
        if self.is_bound:  # shown again (an error): the tags first shown, still to tell them from a change
            self.initial["tags"] = self["tags"].field.hidden_widget().value_from_datadict(
                self.data, self.files, self["tags"].html_initial_name)
        elif self.instance.pk:
            self.initial["tags"] = list(self.instance.tags.values_list("name", flat=True))

    def save(self, commit=True):
        # the host and its tags in one step, not while the Tags page deletes or renames one
        with transaction.atomic():
            lock_ownership()
            compute = super().save(commit)
            if commit and "tags" in self.changed_data:
                compute.tags.set(Tag.named(self.cleaned_data["tags"]))
        return compute


SECRET_WIDGETS = {"password": forms.PasswordInput(), "gstfsd_key": forms.PasswordInput()}
DETAILS = {"details": _("Description")}
DETAILS_HELP = {"details": _("Shown on the hosts list")}
SASL_LABELS = {"login": _("SASL login"), "password": _("SASL password")} | DETAILS


class TcpComputeForm(ComputeTagsMixin, KeepSecretsMixin, forms.ModelForm):
    conn_type = CONN_TCP
    kind = "TCP"
    about = _("libvirt over TCP, with a SASL login")
    hostname = forms.CharField(validators=[validate_hostname])

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = SASL_LABELS
        help_texts = DETAILS_HELP
        exclude = ["type", "tags"]


class SshComputeForm(ComputeTagsMixin, KeepSecretsMixin, forms.ModelForm):
    conn_type = CONN_SSH
    kind = "SSH"
    about = _("libvirt over SSH, with the panel's SSH key")
    hostname = forms.CharField(validators=[validate_hostname], label=_("FQDN/IP"))

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = {"login": _("SSH user")} | DETAILS
        help_texts = DETAILS_HELP
        exclude = ["password", "type", "tags"]


class TlsComputeForm(ComputeTagsMixin, KeepSecretsMixin, forms.ModelForm):
    conn_type = CONN_TLS
    kind = "TLS"
    about = _("libvirt over TLS, with certificates")
    hostname = forms.CharField(validators=[validate_hostname])

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = SASL_LABELS
        help_texts = DETAILS_HELP
        exclude = ["type", "tags"]


class SocketComputeForm(ComputeTagsMixin, KeepSecretsMixin, forms.ModelForm):
    conn_type = CONN_SOCKET
    kind = _("Local")
    about = _("the libvirt of the host the panel runs on, by its socket")
    hostname = forms.CharField(widget=forms.HiddenInput, initial="localhost")

    class Meta:
        model = Compute
        widgets = SECRET_WIDGETS
        labels = DETAILS
        help_texts = DETAILS_HELP
        fields = ["name", "details", "hostname", "migration_address", "migration_tls", "gstfsd_key"]
