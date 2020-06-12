from django.db.models import (CASCADE, BooleanField, CharField, DateField,
                              ForeignKey, Model)
from django.utils.translation import ugettext_lazy as _

from computes.models import Compute


class Instance(Model):
    compute = ForeignKey(Compute, on_delete=CASCADE)
    name = CharField(_('name'), max_length=120)
    uuid = CharField(_('uuid'), max_length=36)
    is_template = BooleanField(_('is template'), default=False)
    created = DateField(_('created'), auto_now_add=True)

    def __unicode__(self):
        return self.name

class PermissionSet(Model):
    """
    Dummy model for holding set of permissions we need to be automatically added by Django
    """
    class Meta:
        default_permissions = ()
        permissions = (
            ('clone_instances', _('Can clone instances')),
        )

        managed = False
