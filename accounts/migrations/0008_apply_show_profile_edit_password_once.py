from django.conf import settings
from django.db import migrations


def apply_setting_once(apps, schema_editor):
    """SHOW_PROFILE_EDIT_PASSWORD was replaced by the change_password
    permission, but its value was applied to every user on each migrate,
    undoing per-user and per-group choices. Apply it one last time."""
    if not hasattr(settings, "SHOW_PROFILE_EDIT_PASSWORD"):
        return
    alias = schema_editor.connection.alias
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    permission = Permission.objects.using(alias).filter(
        content_type__app_label="accounts", codename="change_password"
    ).first()
    if permission is None:  # fresh database: no users and no permissions yet
        return
    for user in User.objects.using(alias).all():
        if settings.SHOW_PROFILE_EDIT_PASSWORD:
            user.user_permissions.add(permission)
        else:
            user.user_permissions.remove(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_userattributes_must_change_password"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(apply_setting_once, migrations.RunPython.noop)]
