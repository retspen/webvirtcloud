from django.db import migrations

CHOICES = "host-model,host-passthrough,maximum"


def fix_cpu_mode(apps, schema_editor):
    """The CPU modes a new VM can have: no-model and custom matched no choice
    of the new VM dialog, which then showed another one. Not undone on the way
    back, as nothing needs the old choices."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    for setting in AppSettings.objects.using(schema_editor.connection.alias).filter(key="INSTANCE_CPU_DEFAULT_MODE"):
        setting.choices = CHOICES
        if setting.value not in CHOICES.split(","):
            setting.value = "host-model"
        setting.save()


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0021_setting_descriptions"),
    ]

    operations = [
        migrations.RunPython(fix_cpu_mode, migrations.RunPython.noop),
    ]
