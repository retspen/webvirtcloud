from django.core.management.color import no_style
from django.db import migrations
from django.utils.translation import gettext_noop as _

SETTING = (_("Session length (hours)"), "LOGIN_SESSION_HOURS", "24",
           _("How long a sign-in lasts; a change applies from the next sign-in"))


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
    dependencies = [("appsettings", "0029_login_notice")]

    operations = [migrations.RunPython(add_setting, del_setting)]
