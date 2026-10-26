from appsettings.settings import app_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.core.validators import MaxLengthValidator
from django.forms import CharField, EmailField, Form, ModelForm, TypedChoiceField, ValidationError
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
            # the ownership being edited is not another owner
            exists = UserInstance.objects.filter(instance=instance).exclude(pk=self.instance.pk)
            if exists:
                raise ValidationError(_("Instance owned by another user"))

        return instance

    class Meta:
        model = UserInstance
        fields = "__all__"


class UniqueEmailMixin:
    """"Lost OTP?" mails only an address that is one user's: a second user
    with the same address would switch it off for both."""

    def clean_email(self):
        email = self.cleaned_data["email"]
        if email and get_user_model().objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(_("Another user has this email address"))
        return email


class ProfileForm(UniqueEmailMixin, ModelForm):
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


class ApiTokenForm(Form):
    name = CharField(label=_("Name"), max_length=64, help_text=_("What uses it, such as a script or a host"))
    days = TypedChoiceField(
        label=_("Expires"), coerce=int, empty_value=None, required=False, initial=90,
        choices=[(30, _("in 30 days")), (90, _("in 90 days")), (365, _("in a year")), ("", _("never"))],
    )


class EmailOTPForm(Form):
    email = EmailField(label=_("Email"))


class BoundedUsernameMixin:
    """Django's login form gives the username its max_length after the field
    is built, so a longer one is not refused and reaches authentication;
    django-axes then cannot store it (PostgreSQL refuses it: 500)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        username = self.fields["username"]
        username.validators.append(MaxLengthValidator(username.max_length))


class LoginForm(BoundedUsernameMixin, AuthenticationForm):
    pass
