from django.db.models import CharField, IntegerField, Model
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _

from vrtManager.connection import connection_manager


class Compute(Model):
    name = CharField(_('name'), max_length=64, unique=True)
    hostname = CharField(_('hostname'), max_length=64)
    login = CharField(_('login'), max_length=20)
    password = CharField(_('password'), max_length=14, blank=True, null=True)
    details = CharField(_('details'), max_length=64, null=True, blank=True)
    type = IntegerField()

    @cached_property
    def status(self):
        return connection_manager.host_is_up(self.type, self.hostname)

    def __str__(self):
        return self.name
