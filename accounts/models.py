from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from instances.models import Instance


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
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)
    keyname = models.CharField(_("key name"), max_length=25)
    keypublic = models.CharField(_("public key"), max_length=500)

    def __str__(self):
        return self.keyname


class UserAttributes(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    can_clone_instances = models.BooleanField(default=True)
    max_instances = models.IntegerField(
        _("max instances"),
        default=2,
        help_text=_("-1 for unlimited. Any integer value"),
        validators=[MinValueValidator(-1)],
    )
    max_cpus = models.IntegerField(
        _("max CPUs"),
        default=2,
        help_text=_("-1 for unlimited. Any integer value"),
        validators=[MinValueValidator(-1)],
    )
    max_memory = models.IntegerField(
        _("max memory"),
        default=2048,
        help_text=_("-1 for unlimited. Any integer value"),
        validators=[MinValueValidator(-1)],
    )
    max_disk_size = models.IntegerField(
        _("max disk size"),
        default=20,
        help_text=_("-1 for unlimited. Any integer value"),
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
