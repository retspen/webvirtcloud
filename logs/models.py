from django.db import models


class Logs(models.Model):
    user = models.CharField(max_length=50)
    instance = models.CharField(max_length=50)
    message = models.CharField(max_length=255)
    date = models.DateTimeField(auto_now=True)

    def __unicode__(self):
        return self.instance
