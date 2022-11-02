from django.db import models
from django.utils.translation import gettext_lazy as _


# Create your models here.
class Storages(models.Model):
    name = models.CharField(
        _("name"),
        max_length=20,
        error_messages={"required": _("No pool name has been entered")},
    )
    status = models.IntegerField(_("status"))
    type = models.CharField(_("type"), max_length=100)
    size = models.IntegerField(_("size"))
    volumes = models.IntegerField(_("volumes"))

    class Meta:
        managed = False

    def __str__(self):
        return f"{self.name}"


class Volume(models.Model):
    name = models.CharField(_("name"), max_length=128)
    type = models.CharField(
        _("format"),
        max_length=12,
        choices=(("qcow2", "qcow2 (recommended)"), ("qcow", "qcow"), ("raw", "raw")),
    )
    allocation = models.IntegerField(_("allocation"))
    size = models.IntegerField(_("size"))

    class Meta:
        managed = False
        verbose_name_plural = "Volumes"

    def __str__(self):
        return f"{self.name}"


class Storage(models.Model):
    state = models.IntegerField(_("state"))
    size = models.IntegerField(_("size"))
    free = models.IntegerField(_("free"))
    status = models.CharField(_("status"), max_length=128)
    path = models.CharField(_("path"), max_length=128)
    type = models.CharField(_("type"), max_length=128)
    autostart = models.BooleanField(_("autostart"))
    volumes = models.ForeignKey(
        Volume, related_name="storage_volumes", on_delete=models.DO_NOTHING
    )

    class Meta:
        managed = False

    def __str__(self):
        return f"{self.path}"
