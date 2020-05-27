from django.db import migrations


def apply_change_password(apps, schema_editor):
    from django.conf import settings
    from django.contrib.auth.models import User, Permission

    if hasattr(settings, 'SHOW_PROFILE_EDIT_PASSWORD'):
        if settings.SHOW_PROFILE_EDIT_PASSWORD:
            permission = Permission.objects.get(codename='change_password')
            users = User.objects.all()
            user: User
            for user in users:
                user.user_permissions.add(permission)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_permissionset'),
    ]

    operations = [
        migrations.RunPython(apply_change_password),
    ]
