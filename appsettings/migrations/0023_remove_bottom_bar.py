from django.db import migrations


def remove_bottom_bar(apps, schema_editor):
    """A VM's page shows its host's links above it, always, as the host's
    pages do: the setting for the bar at the bottom goes."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    AppSettings.objects.using(schema_editor.connection.alias).filter(key="VIEW_INSTANCE_DETAIL_BOTTOM_BAR").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0022_cpu_mode_choices"),
    ]

    operations = [
        migrations.RunPython(remove_bottom_bar, migrations.RunPython.noop),
    ]
