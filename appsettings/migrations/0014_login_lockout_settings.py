from django.core.management.color import no_style
from django.db import migrations
from django.utils.translation import gettext_noop as _


SETTINGS = [
    (_("Login Failure Limit"), "LOGIN_FAILURE_LIMIT", "5",
     _("Failed logins of a user from one address before it is locked")),
    (_("Login Lockout Minutes"), "LOGIN_LOCKOUT_MINUTES", "15",
     _("How long a locked login stays locked, in minutes")),
]


def add_settings(apps, schema_editor):
    setting = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    # Earlier migrations inserted the default rows with fixed ids, which a
    # PostgreSQL id sequence does not see: move it past them before inserting
    # without an id (a no-op on sqlite).
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
    dependencies = [("appsettings", "0013_remove_qemu_console_default_type")]

    operations = [migrations.RunPython(add_settings, del_settings)]
