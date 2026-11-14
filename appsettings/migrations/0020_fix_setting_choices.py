from django.db import migrations

# key: (its choices, the value a removed choice becomes)
FIXES = {
    "CLONE_INSTANCE_DEFAULT_PREFIX": ("", None),  # a text, not True or False
    "INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER": ("virtio-scsi,lsilogic", "virtio-scsi"),  # virtio-blk is no SCSI controller
    "INSTANCE_MACHINE_DEFAULT_TYPE": ("q35,pc,virt", "q35"),  # x86_64 is an architecture
    "INSTANCE_CDROM_ADD": ("None,ide,sata,scsi", "sata"),  # a CD-ROM has no virtio bus
}


def fix_choices(apps, schema_editor):
    """Choices the panel cannot use, a space that kept lsilogic from being
    shown as chosen, and a text setting listed as True or False. Not undone
    on the way back, as nothing needs the old choices."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    for setting in AppSettings.objects.using(schema_editor.connection.alias).filter(key__in=FIXES):
        choices, fallback = FIXES[setting.key]
        setting.choices = choices
        if choices and setting.value not in choices.split(","):
            setting.value = fallback
        setting.save()


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0019_prebuilt_themes"),
    ]

    operations = [
        migrations.RunPython(fix_choices, migrations.RunPython.noop),
    ]
