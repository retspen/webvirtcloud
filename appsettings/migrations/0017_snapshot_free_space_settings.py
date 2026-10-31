from django.core.management.color import no_style
from django.db import migrations
from django.utils.translation import gettext_noop as _


SETTINGS = [
    (_("Snapshot Free Percent"), "SNAPSHOT_FREE_SPACE_PERCENT", "10",
     _("Free space a storage pool keeps for a snapshot, in percent of the VM's disks in it (0: none)")),
    (_("Snapshot Free Min GiB"), "SNAPSHOT_FREE_SPACE_MIN_GIB", "1",
     _("Free space a storage pool keeps for a snapshot at least, in GiB (0: none)")),
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
    dependencies = [("appsettings", "0016_nic_type_rtl8139")]

    operations = [migrations.RunPython(add_settings, del_settings)]
