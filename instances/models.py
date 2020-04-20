from django.db.models import Model, ForeignKey, CharField, BooleanField, DateField, CASCADE
from computes.models import Compute


class Instance(Model):
    compute = ForeignKey(Compute, on_delete=CASCADE)
    name = CharField(max_length=120)
    uuid = CharField(max_length=36)
    is_template = BooleanField(default=False)
    created = DateField(auto_now_add=True)

    def __unicode__(self):
        return self.name
