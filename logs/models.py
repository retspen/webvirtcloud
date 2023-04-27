from django.db.models import CharField, DateTimeField, Model
from django.utils.translation import gettext_lazy as _

class Logs(Model):
    user = CharField(_("user"), max_length=50)
    ip = CharField(_("ip"), max_length=50, default=None, blank=True, null=True)
    host = CharField(_("host"), max_length=50, default="-")
    instance = CharField(_("instance"), max_length=50)
    message = CharField(_("message"), max_length=255)
    date = DateTimeField(_("date"), auto_now=True)

    def __str__(self):
        return self.instance
