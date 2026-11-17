from django import forms
from django.utils.translation import gettext_lazy as _

from computes.models import Compute

from .models import BackupTarget


class TargetPoolForm(forms.Form):
    """A compute's storage pool for a target; computes that have one already are not offered."""

    compute = forms.ModelChoiceField(Compute.objects.all(), label=_("Compute"))
    pool = forms.CharField(label=_("Storage pool"), max_length=128)

    def __init__(self, *args, target=None, **kwargs):
        super().__init__(*args, **kwargs)
        if target is not None:
            self.fields["compute"].queryset = Compute.objects.exclude(backuptargetpool__target=target)


class TargetForm(TargetPoolForm):
    name = forms.CharField(label=_("Name"), max_length=64)
    field_order = ["name", "compute", "pool"]

    def clean_name(self):
        name = self.cleaned_data["name"]
        if BackupTarget.objects.filter(name=name).exists():
            raise forms.ValidationError(_("A backup target with this name exists"))
        return name
