from django import forms
from django.utils.translation import gettext_lazy as _


class AddSecret(forms.Form):
    usage_type = forms.ChoiceField(
        choices=(("ceph", "Ceph"), ("iscsi", "iSCSI"), ("volume", _("Volume")), ("tls", "TLS"), ("vtpm", "vTPM")),
    )
    usage = forms.CharField(strip=False)  # stripped once checked: a line break at its end too
    # a password keeps its spaces; none defines the secret without a value
    value = forms.CharField(required=False, strip=False)
    ephemeral = forms.BooleanField(required=False)
    private = forms.BooleanField(required=False)

    def clean_usage(self):
        usage = self.cleaned_data["usage"]
        # XML text cannot hold them, and libvirt drops a line break
        if any(ord(char) < 32 for char in usage):
            raise forms.ValidationError(_("The usage cannot have control characters or line breaks"))
        if not usage.strip():
            raise forms.ValidationError(self.fields["usage"].error_messages["required"], code="required")
        return usage.strip()


# what a secret's usage and value are, per usage type, for the page's labels
USAGE_TEXTS = {
    "ceph": {"usage": _("Ceph secret name"),
             "usageHelp": _("The name a disk or pool names it by, e.g. client.libvirt secret, not the Ceph user; one secret per name."),
             "value": _("Key"), "valueHelp": _("The key as ceph auth get-key prints it.")},
    "iscsi": {"usage": _("iSCSI target"), "usageHelp": _("The name a disk or pool names it by, e.g. the target IQN."),
              "value": _("CHAP password"), "valueHelp": _("The password as it is typed.")},
    "volume": {"usage": _("Volume path"), "usageHelp": _("The path of the encrypted volume it unlocks."),
               "value": _("Passphrase"), "valueHelp": _("The passphrase as it is typed.")},
    "tls": {"usage": _("Name"), "usageHelp": _("A name for it; qemu.conf names it by its UUID."),
            "value": _("Passphrase"), "valueHelp": _("The passphrase of the TLS key, as it is typed.")},
    "vtpm": {"usage": _("Name"), "usageHelp": _("A name for it; a VM's vTPM names it by its UUID."),
             "value": _("Passphrase"), "valueHelp": _("The passphrase as it is typed.")},
    "none": {"value": _("Value"), "valueHelp": _("The value as it is typed.")},
    "later": _("Leave it blank to give it later."),
}
