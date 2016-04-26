# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_userattributes_max_disk_size'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userattributes',
            name='max_cpus',
            field=models.IntegerField(default=1),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_disk_size',
            field=models.IntegerField(default=20),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_instances',
            field=models.IntegerField(default=1),
        ),
        migrations.AlterField(
            model_name='userattributes',
            name='max_memory',
            field=models.IntegerField(default=2048),
        ),
    ]
