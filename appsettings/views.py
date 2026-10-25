from pathlib import Path

from admin.decorators import superuser_only
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.translation import gettext_noop as _
from logs.audit import audit
from operations.utils import BOUNDS

from appsettings.models import AppSettings


# the themes "manage.py build_themes" compiles; base.html links the chosen one
THEMES_DIR = Path(settings.BASE_DIR, "static", "css", "themes")

# the whole-number settings and their range: they are read as numbers, and a
# letter would break the page or the job that reads one
NUMBERS = {
    **{key: bounds[:2] for key, bounds in BOUNDS.items()},
    "LOGS_PER_PAGE": (1, 1000),
    "LOGIN_FAILURE_LIMIT": (1, 1000),
    "LOGIN_LOCKOUT_MINUTES": (1, 10080),
    "SNAPSHOT_FREE_SPACE_PERCENT": (0, 100),
    "SNAPSHOT_FREE_SPACE_MIN_GIB": (0, 100000),
    "INSTANCE_VOLUME_DEFAULT_OWNER_UID": (0, 4294967294),
    "INSTANCE_VOLUME_DEFAULT_OWNER_GID": (0, 4294967294),
}


def refusal(setting, value):
    """Why the value cannot be saved for the setting, or None."""
    if setting.key in NUMBERS:
        low, high = NUMBERS[setting.key]
        if not (value.isascii() and value.isdigit() and len(value) <= 10 and low <= int(value) <= high):
            return _("%(setting)s must be a whole number between %(low)s and %(high)s") % {
                "setting": setting.name, "low": low, "high": high}
    elif setting.choices and value not in setting.choices_as_list():
        return _("%(setting)s must be one of %(choices)s") % {
            "setting": setting.name, "choices": ", ".join(setting.choices_as_list())}
    return None


@superuser_only
def appsettings(request):
    """
    :param request:
    :return:
    """
    bootstrap_theme = AppSettings.objects.get(key="BOOTSTRAP_THEME")
    themes_list = sorted(p.name.removesuffix(".min.css") for p in THEMES_DIR.glob("*.min.css"))

    # the theme has its own form; the other settings are listed one by one
    appsettings = AppSettings.objects.exclude(
        description__startswith="Bootstrap"
    ).order_by("name")

    if request.method == "POST":
        if "BOOTSTRAP_THEME" in request.POST:
            theme = request.POST.get("BOOTSTRAP_THEME", "")
            if theme not in themes_list:
                messages.error(request, _("Unknown theme: %(theme)s") % {"theme": theme})
                return HttpResponseRedirect(request.get_full_path())
            if theme != bootstrap_theme.value:
                with audit(request, None, "Setting Theme", f"change to {theme}"):
                    bootstrap_theme.value = theme
                    bootstrap_theme.save()
            msg = _("Theme is changed. Now: %(theme)s") % {"theme": theme}
            messages.success(request, msg)
            return HttpResponseRedirect(request.get_full_path())

        for setting in appsettings:
            if setting.key in request.POST:
                value = request.POST.get(setting.key, "")
                refused = refusal(setting, value)
                if refused:
                    messages.error(request, refused)
                    return HttpResponseRedirect(request.get_full_path())
                try:
                    if value != setting.value:
                        with audit(request, None, f"Setting {setting.name}", f"change to {value}"):
                            setting.value = value
                            setting.save()

                    msg = _("%(setting)s is changed. Now: %(value)s") % {
                        "setting": setting.name,
                        "value": setting.value,
                    }
                    messages.success(request, msg)
                except Exception as err:
                    msg = err
                    messages.error(request, msg)
                return HttpResponseRedirect(request.get_full_path())

    return render(request, "appsettings.html", locals())
