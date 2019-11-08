from django.db import models


class Compute(models.Model):
    name = models.CharField(max_length=64)
    hostname = models.CharField(max_length=64)
    login = models.CharField(max_length=20)
    password = models.CharField(max_length=14, blank=True, null=True)
    details = models.CharField(max_length=50, null=True, blank=True)
    type = models.IntegerField()

    def __unicode__(self):
        return self.hostname
