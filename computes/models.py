from django.db.models import Model, CharField, IntegerField


class Compute(Model):
    name = CharField(max_length=64)
    hostname = CharField(max_length=64)
    login = CharField(max_length=20)
    password = CharField(max_length=14, blank=True, null=True)
    details = CharField(max_length=64, null=True, blank=True)
    type = IntegerField()

    def __unicode__(self):
        return self.hostname
