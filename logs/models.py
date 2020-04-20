from django.db.models import Model, CharField, DateTimeField


class Logs(Model):
    user = CharField(max_length=50)
    instance = CharField(max_length=50)
    message = CharField(max_length=255)
    date = DateTimeField(auto_now=True)

    def __unicode__(self):
        return self.instance
