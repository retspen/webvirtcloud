from django.db.models import Model, CharField, IntegerField
from django.utils.translation import ugettext_lazy as _

class Flavor(Model):
    label = CharField(_('label'), max_length=12)
    memory = IntegerField(_('memory'))
    vcpu = IntegerField(_('vcpu'))
    disk = IntegerField(_('disk'))

    def __unicode__(self):
        return self.name
