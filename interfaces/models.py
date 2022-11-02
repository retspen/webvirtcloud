from django.db import models
from django.utils.translation import gettext_lazy as _


# Create your models here.
class Interfaces(models.Model):
    name = models.CharField(
        _("name"),
        max_length=20,
        error_messages={"required": _("No interface name has been entered")},
    )
    type = models.CharField(_("status"), max_length=12)
    state = models.CharField(_("device"), max_length=100)
    mac = models.CharField(_("forward"), max_length=24)

    class Meta:
        managed = False
