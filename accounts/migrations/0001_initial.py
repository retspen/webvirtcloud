from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('instances', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserInstance',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('is_change', models.BooleanField(default=False)),
                ('is_delete', models.BooleanField(default=False)),
                ('instance', models.ForeignKey(to='instances.Instance')),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
