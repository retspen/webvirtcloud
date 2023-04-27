import os

import sass
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
#from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop as _
from logs.views import addlogmsg

from appsettings.models import AppSettings


@login_required
def appsettings(request):
    """
    :param request:
    :return:
    """
    main_css = "wvc-main.min.css"
    sass_dir = AppSettings.objects.get(key="SASS_DIR")
    bootstrap_theme = AppSettings.objects.get(key="BOOTSTRAP_THEME")
    try:
        themes_list = os.listdir(sass_dir.value + "/wvc-themes")
    except FileNotFoundError as err:
        messages.error(request, err)
        addlogmsg(request.user.username, "-", "", err, ip=get_client_ip(request))

    # Bootstrap settings related with filesystems, because of that they are excluded from other settings
    appsettings = AppSettings.objects.exclude(
        description__startswith="Bootstrap"
    ).order_by("name")

    if request.method == "POST":
        if "SASS_DIR" in request.POST:
            try:
                sass_dir.value = request.POST.get("SASS_DIR", "")
                sass_dir.save()

                msg = _("SASS directory path is changed. Now: %(dir)s") % {
                    "dir": sass_dir.value
                }
                messages.success(request, msg)
            except Exception as err:
                msg = err
                messages.error(request, msg)

            addlogmsg(request.user.username, "-", "", msg, ip=get_client_ip(request))
            return HttpResponseRedirect(request.get_full_path())

        if "BOOTSTRAP_THEME" in request.POST:
            theme = request.POST.get("BOOTSTRAP_THEME", "")
            scss_var = f"@import '{sass_dir.value}/wvc-themes/{theme}/variables';"
            # scss_boot = f"@import '{sass_dir.value}/bootstrap/bootstrap.scss';"
            scss_boot = f"@import '{sass_dir.value}/bootstrap-overrides.scss';"
            scss_bootswatch = (
                f"@import '{sass_dir.value}/wvc-themes/{theme}/bootswatch';"
            )

            try:
                with open(sass_dir.value + "/wvc-main.scss", "w") as main:
                    main.write(
                        scss_var + "\n" + scss_boot + "\n" + scss_bootswatch + "\n"
                    )

                css_compressed = sass.compile(
                    string=scss_var + "\n" + scss_boot + "\n" + scss_bootswatch,
                    output_style="compressed",
                )
                with open("static/css/" + main_css, "w") as css:
                    css.write(css_compressed)

                bootstrap_theme.value = theme
                bootstrap_theme.save()

                msg = _("Theme is changed. Now: %(theme)s") % {"theme": theme}
                messages.success(request, msg)
            except Exception as err:
                msg = err
                messages.error(request, msg)

            addlogmsg(request.user.username, "-", "", msg, ip=get_client_ip(request))
            return HttpResponseRedirect(request.get_full_path())

        for setting in appsettings:
            if setting.key in request.POST:
                try:
                    setting.value = request.POST.get(setting.key, "")
                    setting.save()

                    msg = _("%(setting)s is changed. Now: %(value)s") % {
                        "setting": setting.name,
                        "value": setting.value,
                    }
                    messages.success(request, msg)
                except Exception as err:
                    msg = err
                    messages.error(request, msg)

                addlogmsg(request.user.username, "-", "", msg, ip=get_client_ip(request))
                return HttpResponseRedirect(request.get_full_path())

    return render(request, "appsettings.html", locals())

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip