from django.db import migrations


def apply_migration(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Technicians")


class Migration(migrations.Migration):

    dependencies = [
        ("admin", "0002_auto_20200609_0830"),
    ]

    operations = [
        migrations.RunPython(apply_migration, migrations.RunPython.noop),
    ]
