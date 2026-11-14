from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import migrations, models


def flag_legacy_generated_password(apps, schema_editor):
    """Preserve first-login enforcement for installations with a password file."""
    path = Path(settings.BASE_DIR) / "data" / "admin_password"
    try:
        generated = path.read_text().strip()
    except FileNotFoundError:
        return
    except OSError as err:
        raise RuntimeError(
            f"Cannot read {path}; run migrate as its owner to preserve first-login enforcement."
        ) from err
    if not generated:
        return
    alias = schema_editor.connection.alias
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Attributes = apps.get_model("accounts", "UserAttributes")
    for user in User.objects.using(alias).filter(is_superuser=True):
        if check_password(generated, user.password):
            attributes, _ = Attributes.objects.using(alias).get_or_create(
                user_id=user.pk
            )
            attributes.must_change_password = True
            attributes.save(using=alias, update_fields=["must_change_password"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_alter_userattributes_id_alter_userinstance_id_and_more")
    ]
    operations = [
        migrations.AddField(
            model_name="userattributes",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(flag_legacy_generated_password, migrations.RunPython.noop),
    ]
