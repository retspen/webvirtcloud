from django.core.management.color import no_style
from django.db import migrations, models
from django.utils.translation import gettext_noop as _

SETTINGS = (
    (_("Alert e-mail addresses"), "ALERT_EMAILS",
     _("Comma-separated; mailed when a backup fails, is skipped, missing or damaged, or a job is uncertain")),
    (_("Alert webhook"), "ALERT_WEBHOOK", _("An http(s) URL that gets the same alerts as a JSON POST (subject, text, time)")),
)


def add_settings(apps, schema_editor):
    setting = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    # see 0014: move a PostgreSQL id sequence past the fixed ids first
    with schema_editor.connection.cursor() as cursor:
        for sql in schema_editor.connection.ops.sequence_reset_sql(no_style(), [setting]):
            cursor.execute(sql)
    for name, key, description in SETTINGS:
        setting.objects.using(db_alias).get_or_create(
            key=key, defaults={"name": name, "value": "", "choices": "", "description": description})


def del_settings(apps, schema_editor):
    apps.get_model("appsettings", "AppSettings").objects.using(schema_editor.connection.alias).filter(
        key__in=[key for _name, key, _description in SETTINGS]).delete()


class Migration(migrations.Migration):
    dependencies = [("appsettings", "0026_repair_number_settings")]

    operations = [
        migrations.AlterField("appsettings", "value", models.CharField(max_length=255, verbose_name="value")),
        migrations.RunPython(add_settings, del_settings),
    ]
