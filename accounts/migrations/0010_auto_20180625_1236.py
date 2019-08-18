from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_auto_20171026_0805'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userattributes',
            name='max_cpus',
            field=models.IntegerField(default=1, help_text=b'-1 for unlimited. Any integer value'),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_disk_size',
            field=models.IntegerField(default=20, help_text=b'-1 for unlimited. Any integer value'),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_instances',
            field=models.IntegerField(default=1, help_text=b'-1 for unlimited. Any integer value'),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_memory',
            field=models.IntegerField(default=2048, help_text=b'-1 for unlimited. Any integer value'),
        ),
    ]
