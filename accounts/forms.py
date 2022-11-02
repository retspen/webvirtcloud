from appsettings.settings import app_settings
from django.contrib.auth import get_user_model
from django.forms import EmailField, Form, ModelForm, ValidationError
from django.utils.translation import gettext_lazy as _

from .models import UserInstance, UserSSHKey
from .utils import validate_ssh_key


class UserInstanceForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super(UserInstanceForm, self).__init__(*args, **kwargs)

        # Make user and instance fields not editable after creation
        instance = getattr(self, "instance", None)
        if instance and instance.id is not None:
            self.fields["user"].disabled = True
            self.fields["instance"].disabled = True

    def clean_instance(self):
        instance = self.cleaned_data["instance"]
        if app_settings.ALLOW_INSTANCE_MULTIPLE_OWNER == "False":
            exists = UserInstance.objects.filter(instance=instance)
            if exists:
                raise ValidationError(_("Instance owned by another user"))

        return instance

    class Meta:
        model = UserInstance
        fields = "__all__"


class ProfileForm(ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")


class UserSSHKeyForm(ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.publickeys = UserSSHKey.objects.filter(user=self.user)
        super().__init__(*args, **kwargs)

    def clean_keyname(self):
        for key in self.publickeys:
            if self.cleaned_data["keyname"] == key.keyname:
                raise ValidationError(_("Key name already exist"))

        return self.cleaned_data["keyname"]

    def clean_keypublic(self):
        for key in self.publickeys:
            if self.cleaned_data["keypublic"] == key.keypublic:
                raise ValidationError(_("Public key already exist"))

        if not validate_ssh_key(self.cleaned_data["keypublic"]):
            raise ValidationError(_("Invalid key"))
        return self.cleaned_data["keypublic"]

    def save(self, commit=True):
        ssh_key = super().save(commit=False)
        ssh_key.user = self.user
        if commit:
            ssh_key.save()
        return ssh_key

    class Meta:
        model = UserSSHKey
        fields = ("keyname", "keypublic")


class EmailOTPForm(Form):
    email = EmailField(label=_("Email"))
