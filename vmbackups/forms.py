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


class RestoreForm(forms.Form):
    """A backup restored as a new VM, on a compute that has its target's pool."""

    name = forms.CharField(label=_("Name"), max_length=64)
    compute = forms.ModelChoiceField(Compute.objects.none(), label=_("Compute"))
    pool = forms.CharField(label=_("Storage pool for the disks"), max_length=128, initial="default")
    connect = forms.BooleanField(label=_("Connect the network"), required=False,
                                 help_text=_("The restored guest keeps the VM's addresses and host name: "
                                             "connected beside the VM, they clash."))
    start = forms.BooleanField(label=_("Start after restore"), required=False)

    def __init__(self, *args, backup, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["compute"].queryset = Compute.objects.filter(backuptargetpool__target=backup.target).order_by("name")
        self.fields["name"].initial = f"{backup.vm_name}-restored"
