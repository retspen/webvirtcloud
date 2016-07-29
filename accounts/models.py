from django.db import models
from django.contrib.auth.models import User
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
    can_clone_instances = models.BooleanField(default=False)
    max_instances = models.IntegerField(default=1)
    max_cpus = models.IntegerField(default=1)
    max_memory = models.IntegerField(default=2048)
    max_disk_size = models.IntegerField(default=20)

    def __unicode__(self):
        return self.user.username
