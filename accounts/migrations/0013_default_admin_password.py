from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import migrations


def flag_default_admin_password(apps, schema_editor):
    """Versions up to v2.0.0 created the first user as admin/admin. An
    installation that never changed it must replace it at the next login."""
    alias = schema_editor.connection.alias
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Attributes = apps.get_model("accounts", "UserAttributes")
    for user in User.objects.using(alias).filter(username="admin"):
        if check_password("admin", user.password):
            Attributes.objects.using(alias).update_or_create(user_id=user.pk, defaults={"must_change_password": True})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_user_instance_constraint")]
    operations = [migrations.RunPython(flag_default_admin_password, migrations.RunPython.noop)]
