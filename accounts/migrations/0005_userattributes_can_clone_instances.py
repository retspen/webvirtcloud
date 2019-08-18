from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_userattributes'),
    ]

    operations = [
        migrations.AddField(
            model_name='userattributes',
            name='can_clone_instances',
            field=models.BooleanField(default=False),
        ),
    ]
