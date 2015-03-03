from django.db import models
from instances.models import Instance


class Logs(models.Model):
    instance = models.ForeignKey(Instance)
    message = models.CharField(max_length=255)
    date = models.DateTimeField()

    def __unicode__(self):
        return self.instance