# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_merge'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userattributes',
            name='can_clone_instances',
            field=models.BooleanField(default=True),
        ),
    ]
