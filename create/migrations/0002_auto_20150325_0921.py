from django.db import migrations


def add_favors(apps, schema_editor):
    Flavor = apps.get_model("create", "Flavor")
    add_flavor = Flavor(label="micro", vcpu="1", memory="512", disk="20")
    add_flavor.save()
    add_flavor = Flavor(label="mini", vcpu="2", memory="1024", disk="30")
    add_flavor.save()
    add_flavor = Flavor(label="small", vcpu="2", memory="2048", disk="40")
    add_flavor.save()
    add_flavor = Flavor(label="medium", vcpu="2", memory="4096", disk="60")
    add_flavor.save()
    add_flavor = Flavor(label="large", vcpu="4", memory="8192", disk="80")
    add_flavor.save()
    add_flavor = Flavor(label="xlarge", vcpu="8", memory="16384", disk="160")
    add_flavor.save()


class Migration(migrations.Migration):

    dependencies = [
        ('create', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_favors),
    ]
