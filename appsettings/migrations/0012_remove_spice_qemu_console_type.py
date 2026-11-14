from django.db import migrations


def update_console_type(apps, schema_editor):
    AppSettings = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    setting = (
        AppSettings.objects.using(db_alias)
        .filter(key="QEMU_CONSOLE_DEFAULT_TYPE")
        .first()
    )
    if setting:
        setting.value = "vnc"
        setting.choices = "vnc"
        setting.save(using=db_alias)


def reverse_console_type(apps, schema_editor):
    AppSettings = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    setting = (
        AppSettings.objects.using(db_alias)
        .filter(key="QEMU_CONSOLE_DEFAULT_TYPE")
        .first()
    )
    if setting:
        setting.choices = "vnc,spice"
        setting.save(using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0011_alter_appsettings_id"),
    ]

    operations = [
        migrations.RunPython(update_console_type, reverse_console_type),
    ]
