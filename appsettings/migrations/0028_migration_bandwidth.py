from django.core.management.color import no_style
from django.db import migrations
from django.utils.translation import gettext_noop as _

SETTING = (_("Migration bandwidth"), "MIGRATION_BANDWIDTH", "0",
           _("MiB/s for the memory and each copied disk, not the final switchover; 0: libvirt's default"))


def add_setting(apps, schema_editor):
    setting = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    # see 0014: move a PostgreSQL id sequence past the fixed ids first
    with schema_editor.connection.cursor() as cursor:
        for sql in schema_editor.connection.ops.sequence_reset_sql(no_style(), [setting]):
            cursor.execute(sql)
    name, key, value, description = SETTING
    setting.objects.using(db_alias).get_or_create(
        key=key, defaults={"name": name, "value": value, "choices": "", "description": description})


def del_setting(apps, schema_editor):
    apps.get_model("appsettings", "AppSettings").objects.using(schema_editor.connection.alias).filter(
        key=SETTING[1]).delete()


class Migration(migrations.Migration):
    dependencies = [("appsettings", "0027_alert_settings")]

    operations = [migrations.RunPython(add_setting, del_setting)]
