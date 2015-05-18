# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('logs', '0002_auto_20150316_1420'),
    ]

    operations = [
        migrations.AlterField(
            model_name='logs',
            name='instance',
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name='logs',
            name='user',
            field=models.CharField(max_length=50),
        ),
    ]
