# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def add_useradmin(apps, schema_editor):
    from django.contrib.auth.models import User
    # Broken in Django 1.8
    #User.objects.create_superuser("admin", None, "admin")


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_useradmin),
    ]
