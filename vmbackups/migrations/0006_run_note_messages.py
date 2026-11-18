from django.db import migrations, models


class Migration(migrations.Migration):
    """A run's note becomes messages, shown in the reader's language; the
    English notes of earlier runs are dropped."""

    dependencies = [("vmbackups", "0005_owners")]

    operations = [
        migrations.RemoveField(model_name="backuprun", name="note"),
        migrations.AddField(model_name="backuprun", name="note", field=models.JSONField(default=list)),
    ]
