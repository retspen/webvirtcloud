from django.db.models import Model, CharField, DateTimeField
from django.utils.translation import ugettext_lazy as _


class Logs(Model):
    user = CharField(_('user'), max_length=50)
    instance = CharField(_('instance'), max_length=50)
    message = CharField(_('message'), max_length=255)
    date = DateTimeField(_('date'), auto_now=True)

    def __str__(self):
        return self.instance
