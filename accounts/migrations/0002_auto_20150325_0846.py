from django.db import migrations


def add_useradmin(apps, schema_editor):
    from django.utils import timezone
    from django.contrib.auth.models import User

    User.objects.create_superuser('admin', None, 'admin',
                                  last_login=timezone.now()
                                  )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_useradmin),
    ]
