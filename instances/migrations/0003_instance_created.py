from django.db import migrations, models
import datetime


class Migration(migrations.Migration):

    dependencies = [
        ('instances', '0002_instance_is_template'),
    ]

    operations = [
        migrations.AddField(
            model_name='instance',
            name='created',
            field=models.DateField(default=datetime.datetime(2017, 10, 26, 8, 5, 55, 797326), auto_now_add=True),
            preserve_default=False,
        ),
    ]
