from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import ugettext_lazy as _

from instances.models import Instance


class UserInstance(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)
    is_change = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)
    is_vnc = models.BooleanField(default=False)

    def __unicode__(self):
        return self.instance.name


class UserSSHKey(models.Model):
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)
    keyname = models.CharField(_('key name'), max_length=25)
    keypublic = models.CharField(_('public key'), max_length=500)

    def __unicode__(self):
        return self.keyname


class UserAttributes(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    can_clone_instances = models.BooleanField(default=True)
    max_instances = models.IntegerField(_('max instances'),
                                        default=2,
                                        help_text=_("-1 for unlimited. Any integer value"),
                                        validators=[
                                            MinValueValidator(-1),
                                        ])
    max_cpus = models.IntegerField(
        _('max CPUs'),
        default=2,
        help_text=_("-1 for unlimited. Any integer value"),
        validators=[MinValueValidator(-1)],
    )
    max_memory = models.IntegerField(
        _('max memory'),
        default=2048,
        help_text=_("-1 for unlimited. Any integer value"),
        validators=[MinValueValidator(-1)],
    )
    max_disk_size = models.IntegerField(
        _('max disk size'),
        default=20,
        help_text=_("-1 for unlimited. Any integer value"),
        validators=[MinValueValidator(-1)],
    )

    @staticmethod
    def create_missing_userattributes(user):
        try:
            userattributes = user.userattributes
        except UserAttributes.DoesNotExist:
            userattributes = UserAttributes(user=user)
            userattributes.save()

    @staticmethod
    def add_default_instances(user):
        existing_instances = UserInstance.objects.filter(user=user)
        if not existing_instances:
            for instance_name in settings.NEW_USER_DEFAULT_INSTANCES:
                instance = Instance.objects.get(name=instance_name)
                user_instance = UserInstance(user=user, instance=instance)
                user_instance.save()

    @staticmethod
    def configure_user(user):
        UserAttributes.create_missing_userattributes(user)
        UserAttributes.add_default_instances(user)

    def __unicode__(self):
        return self.user.username


class PermissionSet(models.Model):
    """
    Dummy model for holding set of permissions we need to be automatically added by Django
    """
    class Meta:
        default_permissions = ()
        permissions = (('change_password', _('Can change password')), )

        managed = False
