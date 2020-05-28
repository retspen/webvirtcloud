from django import forms
from django.contrib.auth.models import Group, User
from django.utils.translation import ugettext_lazy as _

from accounts.models import UserAttributes

from .models import Permission


class GroupForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=Permission.objects.filter(content_type__model='permissionset'),
        required=False,
    )

    users = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=User.objects.all(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super(GroupForm, self).__init__(*args, **kwargs)
        instance = getattr(self, 'instance', None)
        if instance and instance.id:
            self.fields['users'].initial = self.instance.user_set.all()

    def save_m2m(self):
        self.instance.user_set.set(self.cleaned_data['users'])

    def save(self, *args, **kwargs):
        instance = super(GroupForm, self).save()
        self.save_m2m()
        return instance

    class Meta:
        model = Group
        fields = '__all__'


class UserForm(forms.ModelForm):
    user_permissions = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=Permission.objects.filter(content_type__model='permissionset'),
        label=_('Permissions'),
        required=False,
    )

    groups = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=Group.objects.all(),
        label=_('Groups'),
        required=False,
    )

    class Meta:
        model = User
        fields = [
            'username',
            'groups',
            'first_name',
            'last_name',
            'email',
            'user_permissions',
            'is_staff',
            'is_active',
            'is_superuser',
        ]


class UserCreateForm(UserForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = [
            'username',
            'password',
            'groups',
            'first_name',
            'last_name',
            'email',
            'user_permissions',
            'is_staff',
            'is_active',
            'is_superuser',
        ]


class UserAttributesForm(forms.ModelForm):
    class Meta:
        model = UserAttributes
        exclude = ['user', 'can_clone_instances']
