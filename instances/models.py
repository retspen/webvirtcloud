from computes.models import Compute
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from libvirt import (
    VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL,
    VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL,
    libvirtError,
)
from operations import claims
from operations.models import Claim
from vrtManager.instance import PERSISTENT_XML, wvmInstance
from webvirtcloud.settings import QEMU_CONSOLE_LISTENER_ADDRESSES


class Flavor(models.Model):
    label = models.CharField(_("label"), max_length=12, unique=True)
    memory = models.IntegerField(_("memory"))
    vcpu = models.IntegerField(_("vcpu"))
    disk = models.IntegerField(_("disk"))

    def __str__(self):
        return self.label


class InstanceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related("compute")


class Instance(models.Model):
    compute = models.ForeignKey(Compute, on_delete=models.CASCADE)
    name = models.CharField(_("name"), max_length=120, db_index=True)
    uuid = models.CharField(_("uuid"), max_length=36, db_index=True)
    is_template = models.BooleanField(_("is template"), default=False)
    created = models.DateTimeField(_("created"), auto_now_add=True)
    drbd = models.CharField(_("drbd"), max_length=24, default="None")

    objects = InstanceManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["compute", "uuid"], name="unique_compute_uuid")
        ]

    def __str__(self):
        return f"{self.compute}/{self.name}"

    @cached_property
    def proxy(self):
        return wvmInstance(
            self.compute.hostname,
            self.compute.login,
            self.compute.password,
            self.compute.type,
            self.name,
            uuid=self.uuid,
        )

    @cached_property
    def media(self) -> list[dict]:
        return self.proxy.get_media_devices()

    @cached_property
    def media_iso(self) -> list[str]:
        return sorted(self.proxy.get_iso_media())

    @cached_property
    def disks(self) -> list[dict]:
        return self.proxy.get_disk_devices()

    @cached_property
    def info(self) -> list | None:
        """virDomainGetInfo, read once: state, max memory KiB, memory KiB, vCPUs, CPU time.
        None if the VM cannot be read (host down, VM gone): lists show it as unknown."""
        try:
            return self.proxy.instance.info()
        except libvirtError:
            return None

    @cached_property
    def status(self) -> int:
        return self.proxy.get_status()

    @cached_property
    def autostart(self) -> int:
        return self.proxy.get_autostart()

    @cached_property
    def bootmenu(self) -> bool:
        return self.proxy.get_bootmenu()

    @cached_property
    def boot_order(self) -> dict:
        return self.proxy.get_bootorder()

    @cached_property
    def arch(self) -> str:
        return self.proxy.get_arch()

    @cached_property
    def machine(self) -> str:
        return self.proxy.get_machine_type()

    @cached_property
    def firmware(self) -> dict:
        return self.proxy.get_loader()

    @cached_property
    def nvram(self) -> str | None:
        return self.proxy.get_nvram()

    @cached_property
    def vcpu(self) -> int:
        return self.proxy.get_vcpu()

    @cached_property
    def vcpu_range(self):
        return self.proxy.get_max_cpus()

    @cached_property
    def cur_vcpu(self):
        return self.proxy.get_cur_vcpu()

    @cached_property
    def vcpus(self):
        return self.proxy.get_vcpus()

    @cached_property
    def get_uuid(self):
        return self.proxy.get_uuid()

    @cached_property
    def memory(self) -> int:
        return self.proxy.get_memory()

    @cached_property
    def cur_memory(self):
        return self.proxy.get_cur_memory()

    @cached_property
    def title(self) -> str:
        return self.proxy.get_title()

    @cached_property
    def description(self) -> str:
        return self.proxy.get_description()

    @cached_property
    def networks(self) -> list[dict]:
        return self.proxy.get_net_devices()

    @cached_property
    def config_networks(self) -> list[dict]:
        """NICs of the persistent definition, which the edit and clone forms
        change; target is the running VM's device name, if any."""
        live_targets = {net["mac"]: net.get("target", "") for net in self.networks}
        networks = self.proxy.get_net_devices(config=True)
        for net in networks:
            net["target"] = live_targets.get(net["mac"], "")
        return networks

    @cached_property
    def config_disks(self) -> list[dict]:
        """Disks of the persistent definition, which the disk list, its edit
        form and a clone use: on a running VM a pending change shows, and an
        edit does not post the live value back over it."""
        return self.proxy.get_disk_devices(config=True)

    @cached_property
    def config_vcpu(self) -> int:
        """vCPUs of the persistent definition, which the CPU form changes."""
        return self.proxy.get_vcpu(config=True)

    @cached_property
    def config_cur_vcpu(self) -> int:
        return self.proxy.get_cur_vcpu(config=True)

    @cached_property
    def config_title(self) -> str:
        """Title and description of the persistent definition, which the
        options form changes."""
        return self.proxy.get_title(config=True)

    @cached_property
    def config_description(self) -> str:
        return self.proxy.get_description(config=True)

    @cached_property
    def config_media(self) -> list[dict]:
        """CD-ROMs, boot menu and boot order of the persistent definition,
        which the boot order editor changes."""
        return self.proxy.get_media_devices(config=True)

    @cached_property
    def config_bootmenu(self) -> bool:
        return self.proxy.get_bootmenu(config=True)

    @cached_property
    def config_boot_order(self) -> dict:
        return self.proxy.get_bootorder(config=True)

    @cached_property
    def config_boot_devices(self) -> list[dict]:
        """The disks, CD-ROM drives and NICs the boot order editor lists, those
        in the boot order first in their position; value is as posted, as in
        "disk:vda"."""
        order = [f"{d['dev']}:{d['target']}" for position, d in sorted(self.config_boot_order.items())]
        devices = (
            [{"value": f"disk:{d['dev']}", "name": d["dev"], "kind": _("Disk"), "source": d["image"]}
             for d in self.config_disks]
            + [{"value": f"cdrom:{d['dev']}", "name": d["dev"], "kind": _("CD-ROM"), "source": d["image"]}
               for d in self.config_media]
            + [{"value": f"network:{n['mac']}", "name": n["mac"], "kind": _("NIC"), "source": n["nic"]}
               for n in self.config_networks]
        )
        for device in devices:
            device["checked"] = device["value"] in order
        return sorted(devices, key=lambda d: order.index(d["value"]) if d["checked"] else len(order))

    @cached_property
    def config_video_model(self) -> str | None:
        """Video model and console settings of the persistent definition,
        which their forms change."""
        return self.proxy.get_video_model(config=True)

    @cached_property
    def config_console_type(self) -> str | None:
        return self.proxy.get_console_type(config=True)

    @cached_property
    def config_console_listener_address(self) -> str:
        return self.proxy.get_console_listener_addr(config=True)

    @cached_property
    def config_console_passwd(self):
        return self.proxy.get_console_passwd(config=True)

    @cached_property
    def config_console_keymap(self) -> str:
        return self.proxy.get_console_keymap(config=True)

    @cached_property
    def telnet_port(self):
        return self.proxy.get_telnet_port()

    @cached_property
    def console_type(self) -> str | None:
        return self.proxy.get_console_type()

    @cached_property
    def console_port(self) -> str | None:
        return self.proxy.get_console_port()

    @cached_property
    def console_keymap(self) -> str:
        return self.proxy.get_console_keymap()

    @cached_property
    def console_listener_address(self) -> str:
        return self.proxy.get_console_listener_addr()

    @cached_property
    def guest_agent(self):
        return False if self.proxy.get_guest_agent() is None else True

    @cached_property
    def guest_agent_ready(self) -> bool:
        return self.proxy.is_agent_ready()

    @cached_property
    def video_model(self) -> str | None:
        return self.proxy.get_video_model()

    @cached_property
    def video_models(self):
        return self.proxy.get_video_models(self.arch, self.machine)

    def _snapshots(self, flag):
        return sorted(self.proxy.get_snapshot(flag), reverse=True, key=lambda k: k["date"])

    @cached_property
    def snapshots(self) -> list[dict]:
        return sorted(self.internal_snapshots + self.external_snapshots, reverse=True, key=lambda k: k["date"])

    @cached_property
    def internal_snapshots(self) -> list[dict]:
        return self._snapshots(VIR_DOMAIN_SNAPSHOT_LIST_INTERNAL)

    @cached_property
    def external_snapshots(self) -> list[dict]:
        return self._snapshots(VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL)

    @cached_property
    def snapshot_jobs(self) -> list[dict]:
        # only for the page; create, revert and delete query the jobs again and refuse if that fails
        try:
            return self.proxy.get_snapshot_jobs()
        except libvirtError:
            return []

    @cached_property
    def held_by_job(self) -> bool:
        # a queued job has no libvirt block job yet; a job's claim still holds the VM
        return Claim.objects.filter(resource=claims.instance_key(self.uuid), operation__isnull=False).exists()

    @cached_property
    def inst_xml(self):
        # the definition for the next start, which is the current one while the VM is off
        return self.proxy._XMLDesc(PERSISTENT_XML)

    @cached_property
    def has_managed_save_image(self):
        return self.proxy.get_managed_save_image()

    @cached_property
    def console_passwd(self):
        return self.proxy.get_console_passwd()

    @cached_property
    def cache_modes(self):
        return sorted(self.proxy.get_cache_modes().items())

    @cached_property
    def io_modes(self):
        return sorted(self.proxy.get_io_modes().items())

    @cached_property
    def discard_modes(self):
        return sorted(self.proxy.get_discard_modes().items())

    @cached_property
    def detect_zeroes_modes(self):
        return sorted(self.proxy.get_detect_zeroes_modes().items())

    @cached_property
    def formats(self):
        return self.proxy.get_image_formats()


class MigrateInstance(models.Model):
    instance = models.ForeignKey(
        Instance, related_name="source_host", on_delete=models.DO_NOTHING
    )
    target_compute = models.ForeignKey(
        Compute, related_name="target_host", on_delete=models.DO_NOTHING
    )

    live = models.BooleanField(_("Live"))
    offline = models.BooleanField(_("Offline"))
    autoconverge = models.BooleanField(_("Auto Converge"), default=True)
    compress = models.BooleanField(_("Compress"), default=False)
    unsafe = models.BooleanField(_("Unsafe"), default=False)

    class Meta:
        managed = False


class CreateInstance(models.Model):
    compute = models.ForeignKey(
        Compute, related_name="host", on_delete=models.DO_NOTHING
    )
    name = models.CharField(
        max_length=64,
        error_messages={"required": _("No Virtual Machine name has been entered")},
    )
    firmware = models.CharField(max_length=64)
    vcpu = models.IntegerField(
        error_messages={"required": _("No VCPU has been entered")}, validators=[MinValueValidator(1)]
    )
    # a mode of libvirt's (host-model, host-passthrough, maximum) or a CPU model's name
    vcpu_mode = models.CharField(max_length=64)
    disk = models.IntegerField(blank=True)
    memory = models.IntegerField(
        error_messages={"required": _("No RAM size has been entered")}, validators=[MinValueValidator(1)]
    )
    networks = models.CharField(
        max_length=256,
        error_messages={"required": _("No Network pool has been choosen")},
    )
    nwfilter = models.CharField(max_length=256, blank=True)
    net_model = models.CharField(max_length=256, blank=True)
    storage = models.CharField(max_length=256, blank=True)
    template = models.CharField(max_length=256, blank=True)
    images = models.CharField(max_length=256, blank=True)
    cache_mode = models.CharField(
        max_length=16, error_messages={"required": _("Please select HDD cache mode")}
    )
    hdd_size = models.IntegerField(blank=True, validators=[MinValueValidator(1)])
    meta_prealloc = models.BooleanField(default=False, blank=True)
    virtio = models.BooleanField(default=True)
    qemu_ga = models.BooleanField(default=False)
    mac = models.CharField(max_length=255, blank=True)  # one per NIC, comma separated
    add_cdrom = models.CharField(max_length=16)
    # a NoCloud seed on a CD-ROM: the hostname and the creating user's SSH keys
    cloud_init = models.BooleanField(default=False)
    add_input = models.CharField(max_length=16)
    video = models.CharField(
        max_length=16, error_messages={"required": _("Please select a video driver")}
    )
    listener_addr = models.CharField(
        max_length=20, choices=QEMU_CONSOLE_LISTENER_ADDRESSES
    )

    class Meta:
        managed = False


class InstanceTombstone(models.Model):
    """Ownership of a VM that disappeared from its compute.

    Kept for INSTANCE_OWNERSHIP_RETENTION_DAYS so that the owners come back
    when the same UUID shows up again, on this or another compute.
    """

    uuid = models.CharField(max_length=36, db_index=True)
    name = models.CharField(max_length=120)
    host = models.CharField(max_length=64, blank=True)  # the compute's name: the compute may be deleted
    is_template = models.BooleanField(default=False)
    owners = models.JSONField(default=list)  # [{"user": id, "is_change": .., "is_delete": .., "is_vnc": ..}]
    removed = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return "%s (%s)" % (self.name, self.uuid)


class PermissionSet(models.Model):
    """
    Dummy model for holding set of permissions we need to be automatically added by Django
    """

    class Meta:
        default_permissions = ()
        permissions = [
            ("clone_instances", "Can clone instances"),
            ("passwordless_console", _("Can access console without password")),
            ("view_instances", "Can view instances"),
            ("snapshot_instances", "Can snapshot instances"),
        ]

        managed = False
