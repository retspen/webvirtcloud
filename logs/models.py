from django.db.models import BooleanField, CharField, DateTimeField, GenericIPAddressField, Model, TextField
from django.utils.translation import gettext_lazy as _

class Logs(Model):
    user = CharField(_("user"), max_length=150)
    host = CharField(_("host"), max_length=255, default="-")
    instance = CharField(_("instance"), max_length=120)
    instance_uuid = CharField(_("instance UUID"), max_length=36, blank=True, default="", db_index=True)
    message = TextField(_("message"))
    date = DateTimeField(_("date"), auto_now_add=True, db_index=True)
    success = BooleanField(_("success"), null=True)
    ip = GenericIPAddressField(_("IP address"), null=True)

    def __str__(self):
        return self.instance
