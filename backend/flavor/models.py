from django.db import models
from django.core.validators import validate_slug


class Size(models.Model):

    slug = models.CharField(
        max_length=200,
        validators=[validate_slug],
    )

    name = models.CharField(
        max_length=255,
        blank=True,
    )

    cpu = models.IntegerField(
        default=1,
    )

    disk_bytes = models.BigIntegerField(
        default=21474836480,
    )

    memory_bytes = models.BigIntegerField(
        default=536870912,
    )

    is_active = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    is_deleted = models.BooleanField(
        default=False,
    )

    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ['-id']
        verbose_name = "Instance Size"
        verbose_name_plural = "Instance Sizes"

    def __unicode__(self):
        return self.name

    def save(self):
        if self.ram < 1 * (1024 ** 2):
            self.ram = self.ram * (1024 ** 2)
        if self.disk < 1 * (1024 ** 3):
            self.disk = self.disk * (1024 ** 3)
        super(Size, self).save()


class Image(models.Model):

    slug = models.SlugField(
        max_length=200,
        validators=[validate_slug],
    )

    name = models.CharField(
        max_length=255,
    )

    url = models.URLField(
        max_length=200,
    )

    md5sum = models.CharField(
        max_length=50,
    )

    is_active = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    is_deleted = models.BooleanField(
        default=False,
    )

    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    required_size = models.ForeignKey(
        Size,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    class Meta:
        ordering = ['-id']
        verbose_name = "Instance Image"
        verbose_name_plural = "Instance Images"

    def __unicode__(self):
        return self.name
