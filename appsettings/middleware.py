from .settings import app_settings, get_settings


class AppSettingsMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        get_settings()
        return self.get_response(request)
