from django.db import migrations, models
from django.utils import timezone


def keep_maintenance(apps, schema_editor):
    # a host in maintenance stays in it, from now on
    apps.get_model("computes", "Compute").objects.filter(maintenance=True).update(maintenance_since=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ("computes", "0010_maintenance"),
    ]

    operations = [
        migrations.AddField(
            model_name="compute",
            name="maintenance_since",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(keep_maintenance, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="compute",
            name="maintenance",
        ),
    ]
