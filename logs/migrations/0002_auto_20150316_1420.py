# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('logs', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='logs',
            name='user',
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='logs',
            name='date',
            field=models.DateTimeField(auto_now=True),
            preserve_default=True,
        ),
    ]
