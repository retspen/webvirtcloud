from django.db import models


class AppSettings(models.Model):
    name = models.CharField(max_length=25, null=False)
    key = models.CharField(max_length=50, unique=True)
    value = models.CharField(max_length=25)
    description=models.CharField(max_length=100, null=True)
