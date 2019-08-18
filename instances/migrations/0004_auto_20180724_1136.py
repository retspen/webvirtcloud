from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('instances', '0003_instance_created'),
    ]

    operations = [
        migrations.AlterField(
            model_name='instance',
            name='name',
            field=models.CharField(max_length=120),
        ),
    ]
