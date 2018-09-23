from django.db import models
from django.core.validators import validate_slug


class Region(models.Model):

    slug = models.SlugField(
        max_length=200,
        validators=[validate_slug],
    )

    name = models.CharField(
        max_length=255,
        blank=True,
    )

    is_active = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    is_deleted = models.BooleanField(
        default=False
    )

    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ['-id']
        verbose_name = "Region"
        verbose_name_plural = "Regions"

    def __unicode__(self):
        return self.name
