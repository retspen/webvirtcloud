from django.db import migrations

# the whole-number settings: their range and default. The Settings page now
# refuses other values; one an older version saved ("abc", "0") broke the
# page or job that reads it (int(), a paginator of 0 rows)
NUMBERS = {
    "WORKER_CONCURRENCY": (1, 16, "4"),
    "JOB_RETENTION_DAYS": (1, 3650, "30"),
    "LOG_RETENTION_DAYS": (1, 3650, "365"),
    "LOGS_PER_PAGE": (1, 1000, "100"),
    "LOGIN_FAILURE_LIMIT": (1, 1000, "5"),
    "LOGIN_LOCKOUT_MINUTES": (1, 10080, "15"),
    "SNAPSHOT_FREE_SPACE_PERCENT": (0, 100, "10"),
    "SNAPSHOT_FREE_SPACE_MIN_GIB": (0, 100000, "1"),
    "INSTANCE_VOLUME_DEFAULT_OWNER_UID": (0, 4294967294, "0"),
    "INSTANCE_VOLUME_DEFAULT_OWNER_GID": (0, 4294967294, "0"),
}


def repair(apps, schema_editor):
    """A whole-number setting outside its range, or not a number, goes back
    to its default."""
    AppSettings = apps.get_model("appsettings", "AppSettings")
    for setting in AppSettings.objects.using(schema_editor.connection.alias).filter(key__in=NUMBERS):
        low, high, default = NUMBERS[setting.key]
        value = setting.value.strip()
        if not (value.isascii() and value.isdigit() and low <= int(value) <= high):
            setting.value = default
            setting.save()


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0025_vnc_console_and_nic_descriptions"),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
