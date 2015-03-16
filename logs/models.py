from django.db import models
from instances.models import Instance
from django.contrib.auth.models import User

class Logs(models.Model):
    user = models.ForeignKey(User)
    instance = models.ForeignKey(Instance)
    message = models.CharField(max_length=255)
    date = models.DateTimeField(auto_now=True)

    def __unicode__(self):
        return self.instance