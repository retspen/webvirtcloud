from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db.models import (CASCADE, DO_NOTHING, BooleanField, CharField,
                              ForeignKey, IntegerField, Model, OneToOneField)
from django.utils.translation import ugettext_lazy as _

from instances.models import Instance


class UserInstance(Model):
    user = ForeignKey(User, on_delete=CASCADE)
    instance = ForeignKey(Instance, on_delete=CASCADE)
    is_change = BooleanField(default=False)
    is_delete = BooleanField(default=False)
    is_vnc = BooleanField(default=False)

    def __unicode__(self):
        return self.instance.name


class UserSSHKey(Model):
    user = ForeignKey(User, on_delete=DO_NOTHING)
    keyname = CharField(max_length=25)
    keypublic = CharField(max_length=500)

    def __unicode__(self):
        return self.keyname


class UserAttributes(Model):
    user = OneToOneField(User, on_delete=CASCADE)
    can_clone_instances = BooleanField(default=True)
    max_instances = IntegerField(default=1,
                                 help_text="-1 for unlimited. Any integer value",
                                 validators=[
                                     MinValueValidator(-1),
                                 ])
    max_cpus = IntegerField(
        default=1,
        help_text="-1 for unlimited. Any integer value",
        validators=[MinValueValidator(-1)],
    )
    max_memory = IntegerField(
        default=2048,
        help_text="-1 for unlimited. Any integer value",
        validators=[MinValueValidator(-1)],
    )
    max_disk_size = IntegerField(
        default=20,
        help_text="-1 for unlimited. Any integer value",
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


class PermissionSet(Model):
    """
    Dummy model for holding set of permissions we need to be automatically added by Django
    """
    class Meta:
        default_permissions = ()
        permissions = (
            ('change_password', _('Can change password')),
        )

        managed = False
