import re
from django import forms
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import User


class UserAddForm(forms.Form):
    name = forms.CharField(label="Name",
                           error_messages={'required': _('No User name has been entered')},
                           max_length=20)
    password = forms.CharField(required=True, error_messages={'required': _('No password has been entered')},)
    is_staff = forms.BooleanField(required=True)
    is_superuser = forms.BooleanField(required=True)

    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('^[a-z0-9]+$', name)
        if not have_symbol:
            raise forms.ValidationError(_('The flavor name must not contain any special characters'))
        elif len(name) > 20:
            raise forms.ValidationError(_('The flavor name must not exceed 20 characters'))
        try:
            User.objects.get(username=name)
        except User.DoesNotExist:
            return name
        raise forms.ValidationError(_('Flavor name is already use'))
