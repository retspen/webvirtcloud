from django.db import migrations
from django.utils.translation import gettext_noop as _

# what each setting does, shown under it on the Settings page, translated there
DESCRIPTIONS = {
    "INSTANCE_ARCH_DEFAULT_TYPE": _("Architecture chosen first on the new VM pages"),
    "INSTANCE_MACHINE_DEFAULT_TYPE": _("Machine type chosen first on the new VM pages"),
    "INSTANCE_FIRMWARE_DEFAULT_TYPE": _("Firmware chosen first for a new x86_64 VM"),
    "INSTANCE_CPU_DEFAULT_MODE": _("CPU mode chosen first for a new VM"),
    "INSTANCE_NIC_DEFAULT_TYPE": _("Network card model chosen first for a new VM (default: libvirt's choice)"),
    "INSTANCE_VIDEO_DEFAULT_TYPE": _("Video device chosen first for a new VM"),
    "INSTANCE_INPUT_DEFAULT_DEVICE": _("Input device chosen first for a new VM (None: no input device)"),
    "INSTANCE_CDROM_ADD": _("Bus of the CD-ROM a new VM gets (None: no CD-ROM)"),
    "INSTANCE_VOLUME_DEFAULT_BUS": _("Bus of new disks"),
    "INSTANCE_VOLUME_DEFAULT_FORMAT": _("Format of new disk images in directory pools"),
    "INSTANCE_VOLUME_DEFAULT_CACHE": _("Cache mode of new disks"),
    "INSTANCE_VOLUME_DEFAULT_IO": _("I/O mode of new disks (native needs cache none or directsync)"),
    "INSTANCE_VOLUME_DEFAULT_DISCARD": _("Discard of new disks (unmap: the guest's TRIM frees space in the image)"),
    "INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES": _("Detect zeroes of new disks: how blocks of zeros the guest writes are stored"),
    "INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER": _("Controller model for disks on the SCSI bus"),
    "INSTANCE_VOLUME_DEFAULT_OWNER_UID": _("Owner of new disk image files (0: root; qemu is often 107)"),
    "INSTANCE_VOLUME_DEFAULT_OWNER_GID": _("Group of new disk image files (0: root; qemu is often 107)"),
    "CLONE_INSTANCE_AUTO_NAME": _("Users who are not administrators get clone names made from the prefix"),
    "CLONE_INSTANCE_DEFAULT_PREFIX": _("Prefix of the names made for clones: prefix1, prefix2, ..."),
    "CONSOLE_SCALE": _("The console starts scaled to its window"),
    "CONSOLE_VIEW_ONLY": _("The console starts view-only: no keyboard or mouse input"),
    "CONSOLE_RESIZE_SESSION": _("The console starts asking the guest to fit its screen to the window"),
    "CONSOLE_CLIP_VIEWPORT": _("The console starts clipped to its window, without scaling"),
    "SHOW_ACCESS_ROOT_PASSWORD": _("Show Root Password on a VM's Access tab"),
    "SHOW_ACCESS_SSH_KEYS": _("Show SSH Keys on a VM's Access tab"),
    "ALLOW_INSTANCE_MULTIPLE_OWNER": _("A VM can be given to more than one user"),
    "QUOTA_DEBUG": _("A quota refusal shows the numbers: what would be used and what is allowed"),
    "VIEW_INSTANCES_LIST_STYLE": _("Instances page for administrators: VMs under their host, or one list"),
    "VIEW_INSTANCE_DETAIL_BOTTOM_BAR": _("A VM's page shows a bar with its host's links at the bottom"),
    "VM_DRBD_STATUS": _("The Instances page shows each VM's DRBD state"),
    "LOGS_PER_PAGE": _("Rows per page on the Logs page"),
}


def describe(apps, schema_editor):
    """Descriptions that say what each setting does; they were tooltips
    before, many only repeating the name. Not undone on the way back."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    for setting in AppSettings.objects.using(schema_editor.connection.alias).filter(key__in=DESCRIPTIONS):
        setting.description = DESCRIPTIONS[setting.key]
        setting.save()


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0020_fix_setting_choices"),
    ]

    operations = [
        migrations.RunPython(describe, migrations.RunPython.noop),
    ]
