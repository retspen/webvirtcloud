from django.utils.translation import gettext_lazy as _
from django.db.models import Model, CharField, DateTimeField


class Logs(Model):
    user = CharField(_("user"), max_length=50)
    instance = CharField(_("instance"), max_length=50)
    message = CharField(_("message"), max_length=255)
    date = DateTimeField(_("date"), auto_now=True)

    def __str__(self):
        return self.instance
