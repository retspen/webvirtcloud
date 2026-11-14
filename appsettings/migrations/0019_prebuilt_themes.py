from django.db import migrations


def forward(apps, schema_editor):
    setting = apps.get_model("appsettings", "AppSettings")
    db_alias = schema_editor.connection.alias
    setting.objects.using(db_alias).filter(key="SASS_DIR").delete()
    # the default was a typo that never applied: these installs showed the shipped zephyr
    setting.objects.using(db_alias).filter(key="BOOTSTRAP_THEME", value="flaty").update(value="zephyr")


class Migration(migrations.Migration):
    dependencies = [("appsettings", "0018_worker_settings")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
