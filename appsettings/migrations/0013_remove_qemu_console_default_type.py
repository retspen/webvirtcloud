from django.db import migrations


def remove_console_type(apps, schema_editor):
    """VNC is the only console type; the setting has nothing left to choose."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    AppSettings.objects.using(schema_editor.connection.alias).filter(key="QEMU_CONSOLE_DEFAULT_TYPE").delete()


def restore_console_type(apps, schema_editor):
    AppSettings = apps.get_model("appsettings", "AppSettings")
    AppSettings.objects.using(schema_editor.connection.alias).get_or_create(
        key="QEMU_CONSOLE_DEFAULT_TYPE",
        defaults={"name": "VM Console Type", "value": "vnc", "choices": "vnc", "description": "Default console type"},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0012_remove_spice_qemu_console_type"),
    ]

    operations = [
        migrations.RunPython(remove_console_type, restore_console_type),
    ]
