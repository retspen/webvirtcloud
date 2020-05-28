from django.db import migrations


def migrate_can_clone_instances(apps, schema_editor):
    from django.contrib.auth.models import User, Permission
    user: User
    users = User.objects.all()

    permission = Permission.objects.get(codename='clone_instances')

    for user in users:
        if user.userattributes.can_clone_instances:
            user.user_permissions.add(permission)


def reverse_can_clone_instances(apps, schema_editor):
    from django.contrib.auth.models import User, Permission
    user: User
    users = User.objects.all()

    permission = Permission.objects.get(codename='clone_instances')

    for user in users:
        user.user_permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ('instances', '0002_permissionset'),
    ]

    operations = [
        migrations.RunPython(migrate_can_clone_instances, reverse_can_clone_instances),
    ]
