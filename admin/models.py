from django.contrib.auth.models import Permission as P


class Permission(P):
    """
    Proxy model to Django Permissions model allows us to override __str__
    """

    def __str__(self):
        return f"{self.content_type.app_label}: {self.name}"

    class Meta:
        proxy = True
