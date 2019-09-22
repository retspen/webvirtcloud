import django.core.validators
from django.db import migrations, models
import re


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_auto_20180625_1313'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userattributes',
            name='max_cpus',
            field=models.IntegerField(default=1, help_text=b'-1 for unlimited. Any integer value', validators=[django.core.validators.RegexValidator(re.compile('^-?\\d+\\Z'), code='invalid', message='Enter a valid integer.')]),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_disk_size',
            field=models.IntegerField(default=20, help_text=b'-1 for unlimited. Any integer value', validators=[django.core.validators.RegexValidator(re.compile('^-?\\d+\\Z'), code='invalid', message='Enter a valid integer.')]),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_instances',
            field=models.IntegerField(default=1, help_text=b'-1 for unlimited. Any integer value', validators=[django.core.validators.RegexValidator(re.compile('^-?\\d+\\Z'), code='invalid', message='Enter a valid integer.')]),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_memory',
            field=models.IntegerField(default=2048, help_text=b'-1 for unlimited. Any integer value', validators=[django.core.validators.RegexValidator(re.compile('^-?\\d+\\Z'), code='invalid', message='Enter a valid integer.')]),
        ),
    ]
