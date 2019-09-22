from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_usersshkey'),
    ]

    operations = [
        migrations.AddField(
            model_name='userinstance',
            name='is_vnc',
            field=models.BooleanField(default=False),
        ),
    ]
