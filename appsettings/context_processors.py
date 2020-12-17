from .settings import app_settings as settings


def app_settings(request):
    """
    Simple context processor that puts the config into every\
    RequestContext. Just make sure you have a setting like this::
        TEMPLATE_CONTEXT_PROCESSORS = (
            # ...
            'appsettings.context_processors.app_settings',
        )
    """
    return {"app_settings": settings}
