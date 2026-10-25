from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from instances.models import Instance
from knox.models import AbstractAuthToken


class UserInstanceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related("instance", "user")


class UserInstance(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)
    is_change = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)
    is_vnc = models.BooleanField(default=False)

    objects = UserInstanceManager()

    def __str__(self):
        return _('Instance "%(inst)s" of user %(user)s') % {
            "inst": self.instance,
            "user": self.user,
        }

    class Meta:
        unique_together = ["user", "instance"]


class UserSSHKey(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    keyname = models.CharField(_("key name"), max_length=25)
    keypublic = models.TextField(_("public key"), max_length=16384)

    def __str__(self):
        return self.keyname


class UserAttributes(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    can_clone_instances = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    max_instances = models.IntegerField(
        _("max instances"),
        default=2,
        help_text=_("-1: no limit; 0: none allowed"),
        validators=[MinValueValidator(-1)],
    )
    max_cpus = models.IntegerField(
        _("max CPUs"),
        default=2,
        help_text=_("-1: no limit; 0: none allowed"),
        validators=[MinValueValidator(-1)],
    )
    max_memory = models.IntegerField(
        _("max memory (MiB)"),
        default=2048,
        help_text=_("-1: no limit; 0: none allowed"),
        validators=[MinValueValidator(-1)],
    )
    max_disk_size = models.IntegerField(
        _("max disk size (GiB)"),
        default=20,
        help_text=_("-1: no limit; 0: none allowed"),
        validators=[MinValueValidator(-1)],
    )

    def __str__(self):
        return self.user.username


class PermissionSet(models.Model):
    """
    Dummy model for holding set of permissions we need to be automatically added by Django
    """

    class Meta:
        default_permissions = ()
        permissions = (("change_password", _("Can change password")),)

        managed = False


class ApiToken(AbstractAuthToken):
    """A token for the REST API, kept as a digest (django-rest-knox); the
    name says what uses it."""
    LIMIT = 10  # per user, expired ones not counted

    name = models.CharField(_("name"), max_length=64)
    last_used = models.DateTimeField(_("last used"), null=True, blank=True)

    class Meta:
        ordering = ["-created"]
