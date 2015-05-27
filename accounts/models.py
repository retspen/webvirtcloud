from django.db import models
from django.contrib.auth.models import User
from instances.models import Instance


class UserInstance(models.Model):
    user = models.ForeignKey(User)
    instance = models.ForeignKey(Instance)
    is_change = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)

    def __unicode__(self):
        return self.instance.name


class UserSSHKey(models.Model):
    user = models.ForeignKey(User)
    keyname = models.CharField(max_length=25)
    keypublic = models.CharField(max_length=500)

    def __unicode__(self):
        return self.keyname
