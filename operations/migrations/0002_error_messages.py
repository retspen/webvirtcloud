"""A job's error and its result's warning are lists of messages
(operations.utils.say), so that they are shown in the language of whoever
reads them. Those stored before are one message each, without values: shown
as they were."""

from django.db import migrations, models


def to_messages(apps, schema_editor):
    Operation = apps.get_model("operations", "Operation")
    for op in Operation.objects.exclude(error_text="").only("pk", "error_text"):
        Operation.objects.filter(pk=op.pk).update(error=[{"text": op.error_text, "values": {}}])
    for op in Operation.objects.only("pk", "result"):
        if isinstance(op.result.get("warning"), str):
            Operation.objects.filter(pk=op.pk).update(
                result={**op.result, "warning": [{"text": op.result["warning"], "values": {}}]})


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]

    operations = [
        migrations.RenameField("operation", "error", "error_text"),
        migrations.AddField("operation", "error", models.JSONField(default=list)),
        migrations.RunPython(to_messages, migrations.RunPython.noop),
        migrations.RemoveField("operation", "error_text"),
    ]
