from django.db import migrations
from django.utils.translation import gettext_noop as _

# what these settings do: the console ones apply to a VNC console only (a
# serial console has none of them), and a new VM's NIC model "default" is VirtIO
DESCRIPTIONS = {
    "CONSOLE_SCALE": _("The VNC console starts scaled to its window"),
    "CONSOLE_VIEW_ONLY": _("The VNC console starts view-only: no keyboard or mouse input"),
    "CONSOLE_RESIZE_SESSION": _("The VNC console starts asking the guest to fit its screen to the window"),
    "CONSOLE_CLIP_VIEWPORT": _("The VNC console starts clipped to its window, without scaling"),
    "INSTANCE_NIC_DEFAULT_TYPE": _("Network card model chosen first for a new VM (default: VirtIO)"),
}


def describe(apps, schema_editor):
    AppSettings = apps.get_model("appsettings", "AppSettings")
    for setting in AppSettings.objects.using(schema_editor.connection.alias).filter(key__in=DESCRIPTIONS):
        setting.description = DESCRIPTIONS[setting.key]
        setting.save()


class Migration(migrations.Migration):
    dependencies = [
        ("appsettings", "0024_log_retention_setting"),
    ]

    operations = [
        migrations.RunPython(describe, migrations.RunPython.noop),
    ]
