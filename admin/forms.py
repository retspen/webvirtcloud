from decimal import ROUND_HALF_UP, Decimal

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from accounts.forms import UniqueEmailMixin
from accounts.models import UserAttributes, UserInstance
from appsettings.settings import app_settings
from instances.models import Instance

from .models import Permission


# what each permission lets a user do, shown beside its switch
PERMISSION_HELP = {
    "change_password": _("Change their own password on their profile page"),
    "clone_instances": _("Clone the VMs they may change and the templates they may view, within their quota"),
    "passwordless_console": _("Open a console without the VM's console password"),
    "snapshot_instances": _("Take, revert and delete snapshots of the VMs they may change"),
    "view_instances": _("See every VM and host in the lists, read-only"),
}


def permission_rows(field):
    """Each permission's checkbox of a bound field with what it lets a user do."""
    return [(box, PERMISSION_HELP.get(box.data["value"].instance.codename, "")) for box in field]


class GroupForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=Permission.objects.filter(content_type__model="permissionset"),
        required=False,
    )

    users = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=User.objects.order_by("username"),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super(GroupForm, self).__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        if instance and instance.id:
            self.fields["users"].initial = self.instance.user_set.all()

    def permission_rows(self):
        return permission_rows(self["permissions"])

    def save_m2m(self):
        self.instance.user_set.set(self.cleaned_data["users"])

    def save(self, *args, **kwargs):
        instance = super(GroupForm, self).save()
        self.save_m2m()
        return instance

    class Meta:
        model = Group
        fields = "__all__"


class UserForm(UniqueEmailMixin, forms.ModelForm):
    # one choice for is_staff and is_superuser: a superuser keeps the
    # is_staff it had (it adds nothing to every permission)
    role = forms.ChoiceField(
        widget=forms.RadioSelect,
        choices=[("user", _("User")), ("template_editor", _("Template editor")), ("superuser", _("Superuser"))],
        initial="user",
    )

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
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_superuser:
            self.initial["role"] = "superuser"
        elif self.instance.is_staff:
            self.initial["role"] = "template_editor"

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        if role:
            cleaned["is_superuser"] = self.instance.is_superuser = role == "superuser"
            if role != "superuser":
                self.instance.is_staff = role == "template_editor"
        return cleaned

    def permission_rows(self):
        return permission_rows(self["user_permissions"])

class UserCreateForm(UserForm):
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # New users may change their own password and open their VMs' consoles
        # (whose VNC password the console page sends) unless unticked here
        self.fields["user_permissions"].initial = Permission.objects.filter(
            Q(content_type__app_label="accounts", codename="change_password")
            | Q(content_type__app_label="instances", codename="passwordless_console")
        )

    def clean(self):
        # the VMs a new user owns, by name: a name may repeat across hosts
        cleaned = super().clean()
        self.default_instances = []
        for name in settings.NEW_USER_DEFAULT_INSTANCES:
            found = list(Instance.objects.filter(name=name)[:2])
            if len(found) != 1:
                raise ValidationError(_("NEW_USER_DEFAULT_INSTANCES: %(name)s is not exactly one VM") % {"name": name})
            # as on the VM's Users tab: with one owner allowed, an owned VM is not given a second
            if app_settings.ALLOW_INSTANCE_MULTIPLE_OWNER == "False" and UserInstance.objects.filter(instance=found[0]).exists():
                raise ValidationError(_("NEW_USER_DEFAULT_INSTANCES: %(name)s has an owner, and only one is allowed")
                                      % {"name": name})
            self.default_instances += found
        return cleaned

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
            "is_active",
        ]


# the quota's limits, with the unit each is entered in (memory in GiB, kept in MiB)
QUOTA_UNITS = {"max_instances": "", "max_cpus": "", "max_memory": "GiB", "max_disk_size": "GiB"}


class UserAttributesForm(forms.ModelForm):
    """The quota: each limit a number from 0 (none allowed) or No limit,
    which is kept as -1; memory is entered in GiB and kept in MiB."""

    max_instances = forms.IntegerField(label=_("VMs"), min_value=0, required=False)
    max_cpus = forms.IntegerField(label=_("vCPUs"), min_value=0, required=False)
    max_memory = forms.DecimalField(label=_("Memory"), min_value=0, required=False)
    max_disk_size = forms.IntegerField(label=_("Disk"), min_value=0, required=False)

    class Meta:
        model = UserAttributes
        fields = list(QUOTA_UNITS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in QUOTA_UNITS:
            limit = getattr(self.instance, name)  # a new user's: the model's default
            self.fields[f"{name}_unlimited"] = forms.BooleanField(label=_("No limit"), required=False, initial=limit == -1)
            if limit == -1:
                self.initial[name] = None
            elif name == "max_memory":
                # exact: a MiB count over 1024 always ends, so saving it again changes nothing
                self.initial[name] = format(Decimal(limit) / 1024, "f")
            else:
                self.initial[name] = limit

    def clean(self):
        cleaned = super().clean()
        for name in QUOTA_UNITS:
            if cleaned.get(f"{name}_unlimited"):
                cleaned[name] = -1
            elif cleaned.get(name) is None:
                if name not in self.errors:
                    self.add_error(name, _("Enter a limit or choose No limit."))
            elif name == "max_memory":
                cleaned[name] = int((cleaned[name] * 1024).to_integral_value(ROUND_HALF_UP))
        return cleaned

    def quota_rows(self):
        """Each limit's field, its No limit box and its unit, for the form page."""
        return [(self[name], self[f"{name}_unlimited"], unit) for name, unit in QUOTA_UNITS.items()]


class AdminPasswordForm(AdminPasswordChangeForm):
    """A password an administrator sets; the user may have to change it at their next login."""
    must_change_password = forms.BooleanField(label=_("The user must change it at their next login"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["must_change_password"] = self.fields.pop("must_change_password")  # last, after Django's own
        # Django's "Password-based authentication: Enabled/Disabled", said as how the user signs in
        self.fields["usable_password"].choices = [("true", _("With a password")), ("false", _("Without a password"))]

    def clean(self):
        cleaned = super().clean()
        # the change form asks for the old password: a user without one could never pass it
        if cleaned.get("must_change_password") and not cleaned.get("set_usable_password", True):
            raise ValidationError(_("A user without a password cannot be made to change it"))
        return cleaned
