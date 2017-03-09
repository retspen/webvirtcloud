# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_userattributes_can_clone_instances'),
    ]

    operations = [
        migrations.AddField(
            model_name='userattributes',
            name='max_disk_size',
            field=models.IntegerField(default=0),
        ),
    ]
