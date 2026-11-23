from django.db import migrations, models


def earlier_names(apps, schema_editor):
    """The backups made so far named their files from their UUID only."""
    Backup = apps.get_model("vmbackups", "Backup")
    for backup in Backup.objects.all():
        Backup.objects.filter(pk=backup.pk).update(prefix=f"wvc-{backup.uuid}")


class Migration(migrations.Migration):
    dependencies = [("vmbackups", "0006_run_note_messages")]

    operations = [
        migrations.AddField(model_name="backup", name="prefix", field=models.CharField(default="", max_length=128),
                            preserve_default=False),
        migrations.RunPython(earlier_names, migrations.RunPython.noop),
    ]
