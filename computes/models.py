from ipaddress import ip_address

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import CharField, IntegerField, Model, Q, UniqueConstraint
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError, virConnect

from computes.validators import validate_gstfsd_key, validate_hostname, validate_login, validate_migration_address
from vrtManager.connection import connection_manager
from vrtManager.hostdetails import wvmHostDetails


# what the panel connects to a compute with
ENDPOINT = ("hostname", "login", "password", "type")


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
            "empty: the address the panel reaches the host at"
        ),
    )
    gstfsd_key = CharField(
        _("gstfsd key"),
        max_length=64,
        blank=True,
        default="",
        validators=[validate_gstfsd_key],
        help_text=_(
            "GSTFSD_KEY in the host's /etc/default/webvirt-gstfsd: the panel sets the root password and SSH key "
            "of a shut-off VM with it; empty: they cannot be set there"
        ),
    )

    # the libvirt host's UUID (its capabilities), read when the panel first
    # reaches it: one host is one compute, and a compute's VMs stay on it
    host_uuid = CharField(max_length=36, blank=True, default="", editable=False)

    class Meta:
        constraints = [UniqueConstraint(fields=["host_uuid"], condition=~Q(host_uuid=""), name="one_compute_per_host")]

    @property
    def migration_uri(self):
        """The native migration URI for VMs migrated to this host: its
        migration address, or else the address the panel reaches it at, so
        that the other hosts need not resolve its own name. None, libvirt's
        default (that name), for a host the panel reaches on its loopback."""
        address = self.migration_address or self.hostname
        try:
            ip = ip_address(address)
        except ValueError:
            ip = None
        if not self.migration_address and (address.lower().rstrip(".") == "localhost" or ip and ip.is_loopback):
            return None
        return f"tcp://[{address}]" if ip and ip.version == 6 else f"tcp://{address}"

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

    # The VM list reads these when it renders, after status: a host that
    # stopped answering meanwhile gives None, not an error page.
    @cached_property
    def cpu_count(self):
        try:
            return self.proxy.host_info[2]
        except libvirtError:
            return None

    @cached_property
    def ram_size(self):
        try:
            return self.proxy.host_info[1] * 1048576  # MiB
        except libvirtError:
            return None

    @cached_property
    def ram_usage(self):
        try:
            return self.proxy.get_memory_usage()["percent"]
        except libvirtError:
            return None

    @cached_property
    def capacity(self):
        """What the host has given its VMs (wvmHostDetails.get_capacity) and
        its vCPUs per CPU; or None when the host cannot be read. Not its
        pools: their space is measured by a refresh that scans each pool,
        too slow for pages that read every host (computes.views.host_pools)."""
        if self.status is not True:
            return None
        try:
            given = self.proxy.get_capacity()
        except libvirtError:
            return None
        given["ratio"] = given["vcpus"]["all"] / given["cpus"] if given["cpus"] else 0
        return given

    def __str__(self):
        return self.name

    def record_host(self, uuid=None):
        """Reads (unless given) and keeps the UUID of the host the compute
        reaches (host_uuid) while its connection is still the one read with;
        its UUID, or "" when it cannot be read. IntegrityError when another
        compute is that host."""
        try:
            uuid = uuid or self.proxy.host_uuid()
        except libvirtError:
            return ""
        with transaction.atomic():
            same = {field: getattr(self, field) for field in ENDPOINT}
            if not Compute.objects.filter(pk=self.pk, host_uuid="", **same).update(host_uuid=uuid):
                return ""
        self.host_uuid = uuid
        return uuid

    # why a new or changed connection could not be tried (clean), for the form to tell
    unreachable = None

    def clean(self):
        """A host is one compute, and a compute's VMs stay on their host: a
        new or changed connection is tried and its host UUID read
        (host_uuid). Refused when another compute is that host, or when the
        compute has VMs and the host is not theirs, cannot be reached, or
        theirs is not known. Callers hold hosts_lock (computes.utils)."""
        before = Compute.objects.filter(pk=self.pk).values(*ENDPOINT, "host_uuid").first() if self.pk else None
        if before and all(before[field] == getattr(self, field) for field in ENDPOINT):
            return
        # connected anew: a connection this process still has proves no credentials (another
        # process may have seen them change)
        self.retire_connection()
        try:
            uuid = wvmHostDetails(self.hostname, self.login, self.password, self.type).host_uuid()
        except libvirtError as error:
            uuid, self.unreachable = "", str(error)
        if uuid and (other := Compute.objects.exclude(pk=self.pk).filter(host_uuid=uuid).first()):
            raise ValidationError(_("This host is already added as %(name)s"), params={"name": other.name})
        if before and self.instance_set.exists():
            if not uuid:
                raise ValidationError(_("The panel cannot reach the host to tell that its VMs are there: %(error)s"),
                                      params={"error": self.unreachable})
            try:
                recorded = before["host_uuid"] or Compute.objects.get(pk=self.pk).record_host()
            except IntegrityError:
                recorded = ""
            if not recorded:
                raise ValidationError(_("The host its VMs are on is not known yet: change the connection when "
                                        "the panel has reached the host at its current one"))
            if uuid != recorded:
                raise ValidationError(_("This is another host than the one its VMs are on: "
                                        "add it as a new host"))
        self.host_uuid = uuid

    def retire_connection(self):
        """Its connection as saved is not used again (connection_manager)."""
        connection_manager.retire_connection(self.hostname, self.login, self.password, self.type)

    def save(self, *args, **kwargs):
        before = Compute.objects.filter(pk=self.pk).first() if self.pk else None
        super().save(*args, **kwargs)
        if before and any(getattr(before, field) != getattr(self, field) for field in ENDPOINT):
            before.retire_connection()

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
            deleted = super().delete(*args, **kwargs)
        self.retire_connection()
        return deleted
