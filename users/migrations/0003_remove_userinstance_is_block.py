# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_userinstance_is_block'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userinstance',
            name='is_block',
        ),
    ]
