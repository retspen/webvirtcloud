# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations

class Migration(migrations.Migration):

    dependencies = [
        ('computes', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='Compute',
            name='details',
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
    ]
