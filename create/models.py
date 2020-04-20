from django.db.models import Model, CharField, IntegerField


class Flavor(Model):
    label = CharField(max_length=12)
    memory = IntegerField()
    vcpu = IntegerField()
    disk = IntegerField()

    def __unicode__(self):
        return self.name
