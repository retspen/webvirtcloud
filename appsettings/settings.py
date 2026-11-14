from django.db import DatabaseError

from .models import AppSettings


class Settings:
    pass


app_settings = Settings()


def get_settings():
    try:
        entries = list(AppSettings.objects.all())
    except DatabaseError:
        return  # keep the values already loaded; a failed read must not crash the request
    for entry in entries:
        setattr(app_settings, entry.key, entry.value)
