# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Flavor',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('label', models.CharField(max_length=12)),
                ('memory', models.IntegerField()),
                ('vcpu', models.IntegerField()),
                ('disk', models.IntegerField()),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
