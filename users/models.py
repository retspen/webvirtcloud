from django.db import models
from django.contrib.auth.models import User
from instances.models import Instance


class UserInstance(models.Model):
    user = models.ForeignKey(User)
    instance = models.ForeignKey(Instance)
    is_change = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)
    is_block = models.BooleanField(default=False)

    def __unicode__(self):
        return self.instance.name