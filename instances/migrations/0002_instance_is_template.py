from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('instances', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='instance',
            name='is_template',
            field=models.BooleanField(default=False),
        ),
    ]
