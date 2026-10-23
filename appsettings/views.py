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
                if setting.key in BOUNDS:
                    low, high, _default = BOUNDS[setting.key]
                    raw = request.POST.get(setting.key, "")
                    if not (raw.isascii() and raw.isdigit() and len(raw) <= 4 and low <= int(raw) <= high):
                        messages.error(request, _("%(setting)s must be a whole number between %(low)s and %(high)s")
                                       % {"setting": setting.name, "low": low, "high": high})
                        return HttpResponseRedirect(request.get_full_path())
                value = request.POST.get(setting.key, "")
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
