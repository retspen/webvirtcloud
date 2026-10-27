from ipaddress import ip_address

from django.db import transaction
from django.db.models import CharField, IntegerField, Model
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError, virConnect

from computes.validators import validate_hostname, validate_login, validate_migration_address
from vrtManager.connection import connection_manager
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.storage import wvmStorages


class Compute(Model):
    name = CharField(_("name"), max_length=64, unique=True)
    hostname = CharField(_("hostname"), max_length=64, validators=[validate_hostname])
    login = CharField(_("login"), max_length=32, blank=True, validators=[validate_login])
    password = CharField(_("password"), max_length=255, blank=True, null=True)
    details = CharField(_("details"), max_length=64, null=True, blank=True)
    type = IntegerField()
    migration_address = CharField(
        _("migration address"),
        max_length=64,
        blank=True,
        default="",
        validators=[validate_migration_address],
        help_text=_(
            "IP address or host name the other hosts send migrating VMs to; "
            "empty: the host's own host name, which they must be able to resolve"
        ),
    )

    @property
    def migration_uri(self):
        """The native migration URI for VMs migrated to this host, or None for
        libvirt's default."""
        if not self.migration_address:
            return None
        try:
            if ip_address(self.migration_address).version == 6:
                return f"tcp://[{self.migration_address}]"
        except ValueError:
            pass
        return f"tcp://{self.migration_address}"

    @cached_property
    def status(self):
        """True if WebVirtCloud can connect to the host (within the connect
        timeout; a host that failed recently is not tried again at once)."""
        return isinstance(self.connection, virConnect)

    @cached_property
    def connection_error(self):
        """Why the host cannot be reached, or None."""
        return None if self.status else str(self.connection)

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
    def ram_size(self):
        return self.proxy.get_node_info()[2]

    @cached_property
    def ram_usage(self):
        return self.proxy.get_memory_usage()["percent"]

    @cached_property
    def capacity(self):
        """What the host has given its VMs (wvmHostDetails.get_capacity), its
        vCPUs per CPU, and its active storage pools, the default one first
        (None when the pools cannot be read); or None when the host cannot be
        read."""
        if self.status is not True:
            return None
        try:
            given = self.proxy.get_capacity()
        except libvirtError:
            return None
        given["ratio"] = given["vcpus"]["all"] / given["cpus"] if given["cpus"] else 0
        try:
            storages = wvmStorages(self.hostname, self.login, self.password, self.type)
            pools = [pool for pool in storages.get_storages_info() if pool["status"]]
            given["pools"] = sorted(pools, key=lambda pool: (pool["name"] != "default", pool["name"]))
        except libvirtError:
            given["pools"] = None
        return given

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        """Its VMs keep running on the host: their owners wait in tombstones,
        or follow a VM already listed on another compute. The compute is held
        exclusive, so no reconcile, VM operation or job on it runs meanwhile
        (Busy if one does); its row is locked before its VMs', as the
        reconcile does."""
        from computes.utils import forget, libvirt_compute_lock, lock_ownership

        with libvirt_compute_lock(self), transaction.atomic():
            lock_ownership()
            Compute.objects.select_for_update().filter(pk=self.pk).first()
            for inst in self.instance_set.select_for_update():
                forget(inst)
            return super().delete(*args, **kwargs)
