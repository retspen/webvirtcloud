from django.db.models import CharField, IntegerField, Model
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from libvirt import virConnect

from vrtManager.connection import connection_manager
from vrtManager.hostdetails import wvmHostDetails


class Compute(Model):
    name = CharField(_("name"), max_length=64, unique=True)
    hostname = CharField(_("hostname"), max_length=64)
    login = CharField(_("login"), max_length=20)
    password = CharField(_("password"), max_length=14, blank=True, null=True)
    details = CharField(_("details"), max_length=64, null=True, blank=True)
    type = IntegerField()

    @cached_property
    def status(self):
        # return connection_manager.host_is_up(self.type, self.hostname)
        # TODO: looks like socket has problems connecting via VPN
        if isinstance(self.connection, virConnect):
            return True
        else:
            return self.connection

    @cached_property
    def connection(self):
        try:
            return connection_manager.get_connection(
                self.hostname,
                self.login,
                self.password,
                self.type,
            )
        except Exception as e:
            return e

    @cached_property
    def proxy(self):
        return wvmHostDetails(
            self.hostname,
            self.login,
            self.password,
            self.type,
        )

    @cached_property
    def cpu_count(self):
        return self.proxy.get_node_info()[3]
    
    @cached_property
    def cpu_usage(self):
        return round(self.proxy.get_cpu_usage().get('usage'))

    @cached_property
    def ram_size(self):
        return self.proxy.get_node_info()[2]

    @cached_property
    def ram_usage(self):
        return self.proxy.get_memory_usage()["percent"]

    def __str__(self):
        return self.name
