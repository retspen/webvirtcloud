from django.db import models
from django.utils.translation import gettext_lazy as _


class AppSettings(models.Model):
    def choices_as_list(self):
        return self.choices.split(",")

    name = models.CharField(_("name"), max_length=25, null=False)
    key = models.CharField(_("key"), db_index=True, max_length=50, unique=True)
    value = models.CharField(_("value"), max_length=25)
    choices = models.CharField(_("choices"), max_length=70)
    description = models.CharField(_("description"), max_length=100, null=True)
