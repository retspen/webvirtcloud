from django.db import models


class AppSettings(models.Model):

    def choices_as_list(self):
        return self.choices.split(',')

    name = models.CharField(max_length=25, null=False)
    key = models.CharField(db_index=True, max_length=50, unique=True)
    value = models.CharField(max_length=25)
    choices = models.CharField(max_length=50)
    description = models.CharField(max_length=100, null=True)
