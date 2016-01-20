from django.db import models
from computes.models import Compute


class Instance(models.Model):
    compute = models.ForeignKey(Compute)
    name = models.CharField(max_length=20)
    uuid = models.CharField(max_length=36)
    is_template = models.BooleanField(default=False)

    def __unicode__(self):
        return self.name
