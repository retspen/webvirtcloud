from django.db import models
from django.core.validators import RegexValidator
from region.models import Region


class Compute(models.Model):

    TCP = 1
    TLS = 3
    SSH = 2
    SOCKET = 4
    
    CONN_CHOICES = (
        (TCP, 'TCP'),
        (TLS, 'TLS'),
        (SSH, 'SSH'),
        (SOCKET, 'SOCKET'),
    )

    name = models.CharField(
        max_length=200,
        validators=[RegexValidator('^[a-zA-Z0-9.-_]+$')],
    )

    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
    )

    description = models.CharField(
        max_length=255,
        blank=True,
    )

    address = models.CharField(
        'FQDN or IP Address',
        max_length=50,
        validators=[RegexValidator('^[a-zA-Z0-9._-]+$')],
    )

    login = models.CharField(
        max_length=20,
        blank=True,
    )

    password = models.CharField(
        max_length=20,
        blank=True,
    )

    conn = models.IntegerField(
        choices=CONN_CHOICES,
        default=TCP,
    )

    is_active = models.BooleanField(
        'Active',
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    is_deleted = models.BooleanField(
        'Deleted',
        default=False,
    )

    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ['-id']
        verbose_name = "Compute"
        verbose_name_plural = "Computes"

    def __unicode__(self):
        return self.name
