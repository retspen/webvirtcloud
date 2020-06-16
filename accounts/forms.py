from django.forms import ModelForm, ValidationError
from django.utils.translation import ugettext_lazy as _

from appsettings.models import AppSettings

from .models import UserInstance


class UserInstanceForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super(UserInstanceForm, self).__init__(*args, **kwargs)

        # Make user and instance fields not editable after creation
        instance = getattr(self, 'instance', None)
        if instance and instance.id is not None:
            self.fields['user'].disabled = True
            self.fields['instance'].disabled = True

    def clean_instance(self):
        instance = self.cleaned_data['instance']
        if AppSettings.objects.get(key="ALLOW_INSTANCE_MULTIPLE_OWNER").value == 'False':
            exists = UserInstance.objects.filter(instance=instance)
            if exists:
                raise ValidationError(_('Instance owned by another user'))

        return instance

    class Meta:
        model = UserInstance
        fields = '__all__'
