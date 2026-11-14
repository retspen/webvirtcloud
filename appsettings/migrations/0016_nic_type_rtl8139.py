from django.db import migrations


def fix_rtl8139(apps, schema_editor):
    """The NIC type is rtl8139: a VM with model rt18139 does not start. Not
    undone on the way back, as nothing needs the misspelling."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    for setting in AppSettings.objects.using(schema_editor.connection.alias).filter(key="INSTANCE_NIC_DEFAULT_TYPE"):
        setting.choices = setting.choices.replace("rt18139", "rtl8139")
        if setting.value == "rt18139":
            setting.value = "rtl8139"
        setting.save()


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0015_remove_clone_instance_auto_migrate"),
    ]

    operations = [
        migrations.RunPython(fix_rtl8139, migrations.RunPython.noop),
    ]
