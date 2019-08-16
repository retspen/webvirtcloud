from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('computes', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Instance',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=20)),
                ('uuid', models.CharField(max_length=36)),
                ('compute', models.ForeignKey(to='computes.Compute')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
