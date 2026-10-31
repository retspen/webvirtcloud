from django.core.management.color import no_style
from django.db import migrations
from django.utils.translation import gettext_noop as _


SETTINGS = [
    (_("Worker Concurrency"), "WORKER_CONCURRENCY", "4", _("Jobs the worker runs at the same time (1-16)")),
    (_("Job Retention Days"), "JOB_RETENTION_DAYS", "30", _("Days finished jobs stay in the job history (1-3650)")),
]


def add_settings(apps, schema_editor):
    setting = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    # see 0014: move a PostgreSQL id sequence past the fixed ids first
    with schema_editor.connection.cursor() as cursor:
        for sql in schema_editor.connection.ops.sequence_reset_sql(no_style(), [setting]):
            cursor.execute(sql)
    for name, key, value, description in SETTINGS:
        setting.objects.using(db_alias).get_or_create(
            key=key, defaults={"name": name, "value": value, "choices": "", "description": description}
        )


def del_settings(apps, schema_editor):
    setting = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    setting.objects.using(db_alias).filter(key__in=[key for _, key, _, _ in SETTINGS]).delete()


class Migration(migrations.Migration):
    dependencies = [("appsettings", "0017_snapshot_free_space_settings")]

    operations = [migrations.RunPython(add_settings, del_settings)]
