from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from instances.models import Instance


class UserInstance(models.Model):
    user = models.ForeignKey(User)
    instance = models.ForeignKey(Instance)
    is_change = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)
    is_vnc = models.BooleanField(default=False)

    def __unicode__(self):
        return self.instance.name


class UserSSHKey(models.Model):
    user = models.ForeignKey(User)
    keyname = models.CharField(max_length=25)
    keypublic = models.CharField(max_length=500)

    def __unicode__(self):
        return self.keyname

class UserAttributes(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    can_clone_instances = models.BooleanField(default=True)
    max_instances = models.IntegerField(default=1)
    max_cpus = models.IntegerField(default=1)
    max_memory = models.IntegerField(default=2048)
    max_disk_size = models.IntegerField(default=20)

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
