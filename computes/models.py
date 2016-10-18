from django.db import models


class Compute(models.Model):
    name = models.CharField(max_length=20)
    hostname = models.CharField(max_length=20)
    login = models.CharField(max_length=20)
    password = models.CharField(max_length=14, blank=True, null=True)
    type = models.IntegerField()
    gstfsd_key = models.CharField(max_length=256, blank=True, null=True)

    def __unicode__(self):
        return self.hostname
