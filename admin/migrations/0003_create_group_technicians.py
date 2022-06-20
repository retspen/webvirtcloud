from django.db import models, migrations

def apply_migration(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.create(name='Technicians')

class Migration(migrations.Migration):

    dependencies = [
            ('admin', '0002_auto_20200609_0830'),
            ]

    operations = [
            migrations.RunPython(apply_migration)
            ]
