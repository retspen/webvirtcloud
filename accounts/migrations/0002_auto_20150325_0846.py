# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.contrib.auth.models import User

def add_admin(apps, schema_editor):
    add_user = User.objects.create_user("admin", None, "admin")
    add_user.is_active = True
    add_user.is_superuser = True
    add_user.is_staff = True
    add_user.save()

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_admin),
    ]