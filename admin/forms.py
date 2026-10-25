from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from accounts.models import UserAttributes

from .models import Permission


class GroupForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=Permission.objects.filter(content_type__model="permissionset"),
        required=False,
    )

    users = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=User.objects.all(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super(GroupForm, self).__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        if instance and instance.id:
            self.fields["users"].initial = self.instance.user_set.all()

    def save_m2m(self):
        self.instance.user_set.set(self.cleaned_data["users"])

    def save(self, *args, **kwargs):
        instance = super(GroupForm, self).save()
        self.save_m2m()
        return instance

    class Meta:
        model = Group
        fields = "__all__"


class UserForm(forms.ModelForm):
    user_permissions = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=Permission.objects.filter(content_type__model="permissionset"),
        label=_("Permissions"),
        required=False,
    )

    groups = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=Group.objects.all(),
        label=_("Groups"),
        required=False,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "groups",
            "first_name",
            "last_name",
            "email",
            "user_permissions",
            "is_staff",
            "is_active",
            "is_superuser",
        ]
        labels = {"is_staff": _("Template editor")}
        help_texts = {"is_staff": _("May change and delete the template VMs given to them")}


class UserCreateForm(UserForm):
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # New users may change their own password unless unticked here
        self.fields["user_permissions"].initial = Permission.objects.filter(
            content_type__app_label="accounts", codename="change_password"
        )

    def _post_clean(self):
        # The validators in AUTH_PASSWORD_VALIDATORS, as on the password change
        # forms; after the instance has the form's values (username, email).
        super()._post_clean()
        password = self.cleaned_data.get("password")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except ValidationError as error:
                self.add_error("password", error)

    def save(self, commit=True):
        # hashed before the user is first written: the raw password never
        # reaches the database
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            self.save_m2m()
        return user

    class Meta(UserForm.Meta):
        fields = [
            "username",
            "password",
            "groups",
            "first_name",
            "last_name",
            "email",
            "user_permissions",
            "is_staff",
            "is_active",
            "is_superuser",
        ]


class UserAttributesForm(forms.ModelForm):
    class Meta:
        model = UserAttributes
        exclude = ["user", "can_clone_instances", "must_change_password"]


class AdminPasswordForm(AdminPasswordChangeForm):
    """A password an administrator sets; the user may have to change it at their next login."""
    must_change_password = forms.BooleanField(label=_("The user must change it at their next login"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["must_change_password"] = self.fields.pop("must_change_password")  # last, after Django's own

    def clean(self):
        cleaned = super().clean()
        # the change form asks for the old password: a user without one could never pass it
        if cleaned.get("must_change_password") and not cleaned.get("set_usable_password", True):
            raise ValidationError(_("A user without a password cannot be made to change it"))
        return cleaned
