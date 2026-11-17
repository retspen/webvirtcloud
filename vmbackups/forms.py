from django import forms
from django.utils.translation import gettext_lazy as _

from computes.models import Compute
from instances.models import Instance

from .models import BackupPolicy, BackupTarget


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

    def __init__(self, *args, backup, place=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["compute"].queryset = Compute.objects.filter(backuptargetpool__target=backup.target).order_by("name")
        self.fields["name"].initial = f"{backup.vm_name}-restored"
        if place:  # a VM owner's: the VM's compute and pool, shown on the page
            del self.fields["compute"], self.fields["pool"]


class RestoreDiskForm(forms.Form):
    """One disk of a backup restored as a new volume, attached to no VM."""

    dev = forms.ChoiceField(label=_("Disk"))
    compute = forms.ModelChoiceField(Compute.objects.none(), label=_("Compute"))
    pool = forms.CharField(label=_("Storage pool"), max_length=128, initial="default")
    name = forms.CharField(label=_("Volume name"), max_length=255)

    def __init__(self, *args, backup, **kwargs):
        super().__init__(*args, **kwargs)
        disks = list(backup.files.filter(role="disk").order_by("dev"))
        self.fields["dev"].choices = [(d.dev, d.dev) for d in disks]
        self.fields["compute"].queryset = Compute.objects.filter(backuptargetpool__target=backup.target).order_by("name")
        if disks:
            first = disks[0]
            self.fields["name"].initial = f"{backup.vm_name}-{first.dev}-restored.{'qcow2' if first.format == 'qcow2' else 'raw'}"


class PolicyForm(forms.ModelForm):
    """A backup schedule: a compute's VMs or chosen VMs, all on hosts that
    have a pool of its target."""

    class Meta:
        model = BackupPolicy
        fields = ["name", "target", "compute", "instances", "time", "keep", "full_every", "frozen", "enabled"]
        labels = {"name": _("Name"), "target": _("Backup target"), "compute": _("Every VM of a compute"),
                  "instances": _("Or these VMs"), "time": _("Daily at"), "keep": _("Backups to keep of each VM"),
                  "full_every": _("A full backup every N backups"),
                  "frozen": _("Require frozen file systems"), "enabled": _("Enabled")}
        widgets = {"time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "instances": forms.SelectMultiple(attrs={"data-searchable": "1"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["instances"].queryset = Instance.objects.filter(is_template=False).select_related("compute").order_by(
            "name")
        self.fields["instances"].label_from_instance = lambda vm: f"{vm.name} ({vm.compute.name})"
        for name in ("keep", "full_every"):
            self.fields[name].validators.append(_min_one)
            self.fields[name].widget.attrs["min"] = 1
        self.fields["full_every"].help_text = _("1: every backup is full. Above 1, the backups between copy only what "
                                                "changed (running VMs with qcow2 disks).")

    def clean(self):
        data = super().clean()
        compute, vms, target = data.get("compute"), data.get("instances"), data.get("target")
        if bool(compute) == bool(vms):
            raise forms.ValidationError(_("Choose a compute or VMs, not both"))
        if target is not None:
            hosts = {compute} if compute else {vm.compute for vm in vms}
            for host in sorted(hosts, key=lambda c: c.name):
                if target.pool_on(host) is None:
                    raise forms.ValidationError(_("Backup target %(target)s has no storage pool on %(compute)s"),
                                                params={"target": target.name, "compute": host.name})
        return data


def _min_one(value):
    if value < 1:
        raise forms.ValidationError(_("Keep one backup at least"))
