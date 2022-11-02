from django.db import models
from django.utils.translation import gettext_lazy as _


# Create your models here.
class Networks(models.Model):
    name = models.CharField(
        _("name"),
        max_length=20,
        error_messages={"required": _("No network name has been entered")},
    )
    status = models.CharField(_("status"), max_length=12)
    device = models.CharField(_("device"), max_length=100)
    forward = models.CharField(_("forward"), max_length=24)

    class Meta:
        managed = False
