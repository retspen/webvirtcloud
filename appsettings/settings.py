from .models import AppSettings


class Settings(object):
    pass


app_settings = Settings()


def get_settings():
    try:
        entries = AppSettings.objects.all()
    except:
        pass

    for entry in entries:
        setattr(app_settings, entry.key, entry.value)
