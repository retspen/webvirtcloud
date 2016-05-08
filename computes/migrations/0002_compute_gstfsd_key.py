# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('computes', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='compute',
            name='gstfsd_key',
            field=models.CharField(max_length=256, null=True, blank=True),
        ),
    ]
