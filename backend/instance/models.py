from django.db import models
from django.conf import settings

from region.models import Region
from compute.models import Compute
from flavor.models import Size, Image


class Instance(models.Model):

    ACTIVE = 1
    INACTIVE = 0
    STATUS_CHOICES = (
        (ACTIVE, 'active'),
        (INACTIVE, 'inactive'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
    )

    name = models.CharField(
        max_length=255,
    )

    status = models.IntegerField(
        choices=STATUS_CHOICES,
        default=INACTIVE,
    )

    uuid = models.CharField(
        max_length=40,
        blank=True,
        null=True,
    )

    compute = models.ForeignKey(
        Compute,
        blank=True,
        null=True,
    )

    size = models.ForeignKey(
        Size,
    )

    image = models.ForeignKey(
        Image,
        on_delete=models.CASCADE,
    )

    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
    )

    disk_bytes = models.BigIntegerField(
        default=21474836480,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    is_task = models.BooleanField(
        default=True,
    )

    task_id = models.IntegerField(
        default=1,
    )

    is_private_network = models.BooleanField(
        default=False,
    )

    is_locked = models.BooleanField(
        default=False,
    )

    is_deleted = models.BooleanField(
        default=False,
    )

    public_net_mac = models.CharField(
        max_length=18,
        default="52:54:00:01:02:03",
    )

    private_net_mac = models.CharField(
        max_length=18,
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ['-id']
        verbose_name = "Instance"
        verbose_name_plural = "Instances"

    def __unicode__(self):
        return str(self.name)
