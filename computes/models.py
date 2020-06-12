from django.db.models import Model, CharField, IntegerField
from django.utils.translation import ugettext_lazy as _

class Compute(Model):
    name = CharField(_('name'), max_length=64, unique=True)
    hostname = CharField(_('hostname'), max_length=64)
    login = CharField(_('login'), max_length=20)
    password = CharField(_('password'), max_length=14, blank=True, null=True)
    details = CharField(_('details'), max_length=64, null=True, blank=True)
    type = IntegerField()

    def __unicode__(self):
        return self.hostname
