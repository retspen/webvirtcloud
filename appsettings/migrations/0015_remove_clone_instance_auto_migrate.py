from django.db import migrations


def remove_auto_migrate(apps, schema_editor):
    """A clone stays on the host of the VM it was made from: the setting sent
    it to a random host, whatever storage, CPU or network that host had."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    AppSettings.objects.using(schema_editor.connection.alias).filter(key="CLONE_INSTANCE_AUTO_MIGRATE").delete()


def restore_auto_migrate(apps, schema_editor):
    AppSettings = apps.get_model("appsettings", "AppSettings")
    AppSettings.objects.using(schema_editor.connection.alias).get_or_create(
        key="CLONE_INSTANCE_AUTO_MIGRATE",
        defaults={
            "name": "VM Clone Auto Migrate",
            "value": "False",
            "choices": "True,False",
            "description": "Auto migrate instance after clone",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0014_login_lockout_settings"),
    ]

    operations = [
        migrations.RunPython(remove_auto_migrate, restore_auto_migrate),
    ]
