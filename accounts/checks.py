from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security)
def password_change_middleware_check(app_configs, **kwargs):
    middleware = list(settings.MIDDLEWARE)
    required = "accounts.middleware.ForcePasswordChangeMiddleware"
    authentication = "django.contrib.auth.middleware.AuthenticationMiddleware"
    if required not in middleware or (
        authentication in middleware
        and middleware.index(required) < middleware.index(authentication)
    ):
        return [
            Error(
                "ForcePasswordChangeMiddleware must follow AuthenticationMiddleware.",
                hint=f"data/local_settings.py sets MIDDLEWARE: keep '{required}' after AuthenticationMiddleware, as webvirtcloud/settings.py has it.",
                id="accounts.E001",
            )
        ]
    return []


@register(Tags.security)
def login_required_middleware_check(app_configs, **kwargs):
    middleware = list(settings.MIDDLEWARE)
    required = "webvirtcloud.middleware.LoginRequiredMiddleware"
    django_s = "django.contrib.auth.middleware.LoginRequiredMiddleware"
    old = "login_required.middleware.LoginRequiredMiddleware"
    if django_s in middleware and old not in middleware:
        # it signs in as well; a page whose session ended does not say so, and a form sent then is lost
        return [
            Warning(
                "MIDDLEWARE uses Django's LoginRequiredMiddleware, not the panel's.",
                hint=f"data/local_settings.py sets MIDDLEWARE: replace '{django_s}' with '{required}', "
                "as webvirtcloud/settings.py has it.",
                id="accounts.W002",
            )
        ]
    if old in middleware or required not in middleware:
        return [
            Error(
                "MIDDLEWARE must use the panel's LoginRequiredMiddleware.",
                hint=f"data/local_settings.py sets MIDDLEWARE: replace '{old}' with '{required}' "
                "and delete LOGIN_REQUIRED_IGNORE_VIEW_NAMES, as webvirtcloud/settings.py has it.",
                id="accounts.E002",
            )
        ]
    return []


@register()
def obsolete_settings_check(app_configs, **kwargs):
    if hasattr(settings, "SHOW_PROFILE_EDIT_PASSWORD"):
        return [
            Warning(
                "SHOW_PROFILE_EDIT_PASSWORD is no longer used.",
                hint="Remove it from data/local_settings.py. Whether a user may change their own "
                "password is the 'Can change password' permission, per user or group.",
                id="accounts.W001",
            )
        ]
    return []

