from django import forms
from django.utils.translation import gettext_lazy as _


class AddSecret(forms.Form):
    usage_type = forms.ChoiceField(
        choices=(("ceph", "Ceph"), ("iscsi", "iSCSI"), ("volume", _("Volume")), ("tls", "TLS"), ("vtpm", "vTPM")),
    )
    usage = forms.CharField()
    # a password keeps its spaces; none defines the secret without a value
    value = forms.CharField(required=False, strip=False)
    ephemeral = forms.BooleanField(required=False)
    private = forms.BooleanField(required=False)
