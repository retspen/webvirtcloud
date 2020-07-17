from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from libvirt import VIR_DOMAIN_XML_SECURE

from computes.models import Compute
from vrtManager.instance import wvmInstance


class Flavor(models.Model):
    label = models.CharField(_('label'), max_length=12, unique=True)
    memory = models.IntegerField(_('memory'))
    vcpu = models.IntegerField(_('vcpu'))
    disk = models.IntegerField(_('disk'))

    def __str__(self):
        return self.label


class InstanceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('compute')


class Instance(models.Model):
    compute = models.ForeignKey(Compute, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=120, db_index=True)
    uuid = models.CharField(_('uuid'), max_length=36, db_index=True)
    is_template = models.BooleanField(_('is template'), default=False)
    created = models.DateTimeField(_('created'), auto_now_add=True)

    objects = InstanceManager()

    def __str__(self):
        return f'{self.compute}/{self.name}'

    @cached_property
    def proxy(self):
        return wvmInstance(
            self.compute.hostname,
            self.compute.login,
            self.compute.password,
            self.compute.type,
            self.name,
        )

    @cached_property
    def media(self):
        return self.proxy.get_media_devices()

    @cached_property
    def media_iso(self):
        return sorted(self.proxy.get_iso_media())

    @cached_property
    def disks(self):
        return self.proxy.get_disk_devices()

    @cached_property
    def status(self):
        return self.proxy.get_status()

    @cached_property
    def autostart(self):
        return self.proxy.get_autostart()

    @cached_property
    def bootmenu(self):
        return self.proxy.get_bootmenu()

    @cached_property
    def boot_order(self):
        return self.proxy.get_bootorder()

    @cached_property
    def arch(self):
        return self.proxy.get_arch()

    @cached_property
    def machine(self):
        return self.proxy.get_machine_type()

    @cached_property
    def firmware(self):
        return self.proxy.get_loader()

    @cached_property
    def nvram(self):
        return self.proxy.get_nvram()

    @cached_property
    def vcpu(self):
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
    def memory(self):
        return self.proxy.get_memory()

    @cached_property
    def cur_memory(self):
        return self.proxy.get_cur_memory()

    @cached_property
    def title(self):
        return self.proxy.get_title()

    @cached_property
    def description(self):
        return self.proxy.get_description()

    @cached_property
    def networks(self):
        return self.proxy.get_net_devices()

    @cached_property
    def qos(self):
        return self.proxy.get_all_qos()

    @cached_property
    def telnet_port(self):
        return self.proxy.get_telnet_port()

    @cached_property
    def console_type(self):
        return self.proxy.get_console_type()

    @cached_property
    def console_port(self):
        return self.proxy.get_console_port()

    @cached_property
    def console_keymap(self):
        return self.proxy.get_console_keymap()

    @cached_property
    def console_listen_address(self):
        return self.proxy.get_console_listen_addr()

    @cached_property
    def guest_agent(self):
        return False if self.proxy.get_guest_agent() is None else True

    @cached_property
    def guest_agent_ready(self):
        return self.proxy.is_agent_ready()

    @cached_property
    def video_model(self):
        return self.proxy.get_video_model()

    @cached_property
    def video_models(self):
        return self.proxy.get_video_models(self.arch, self.machine)

    @cached_property
    def snapshots(self):
        return sorted(self.proxy.get_snapshot(), reverse=True, key=lambda k: k['date'])

    @cached_property
    def inst_xml(self):
        return self.proxy._XMLDesc(VIR_DOMAIN_XML_SECURE)

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


class PermissionSet(models.Model):
    """
    Dummy model for holding set of permissions we need to be automatically added by Django
    """
    class Meta:
        default_permissions = ()
        permissions = [('clone_instances', 'Can clone instances'),  
                       ('passwordless_console',  _('Can access console without password')),
                    ]

        managed = False
