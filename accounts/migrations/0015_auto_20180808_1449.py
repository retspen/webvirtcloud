from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_auto_20180808_1436'),
    ]

    operations = [
        migrations.AlterField(
            model_name='usersshkey',
            name='user',
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING),
        ),
    ]
