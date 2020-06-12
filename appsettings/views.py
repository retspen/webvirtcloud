import sass
import os

from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from appsettings.models import AppSettings
from logs.views import addlogmsg



@login_required
def appsettings(request):
    """
    :param request:
    :return:
    """
    error_messages = []
    main_css = "wvc-main.min.css"
    sass_dir = AppSettings.objects.get(key="SASS_DIR")
    bootstrap_theme = AppSettings.objects.get(key="BOOTSTRAP_THEME")
    try:
        themes_list = os.listdir(sass_dir.value + "/wvc-theme")
    except FileNotFoundError as err:
        error_messages.append(err)
        addlogmsg(request.user.username, "", err)   

    # Bootstrap settings related with filesystems, because of that they are excluded from other settings
    appsettings = AppSettings.objects.exclude(description__startswith="Bootstrap").order_by("name")
    

    if request.method == 'POST':
        if 'SASS_DIR' in request.POST:
            try:
                sass_dir.value = request.POST.get("SASS_DIR", "")
                sass_dir.save()

                msg = _(f"SASS directory path is changed. Now: {sass_dir.value}")
                messages.success(request, msg)
            except Exception as err:
                msg = err
                error_messages.append(msg)
            
            addlogmsg(request.user.username, "", msg)
            return HttpResponseRedirect(request.get_full_path())

        if 'BOOTSTRAP_THEME' in request.POST:
            theme = request.POST.get("BOOTSTRAP_THEME", "")
            scss_var = f"@import '{sass_dir.value}/wvc-theme/{theme}/variables';"
            scss_bootswatch = f"@import '{sass_dir.value}/wvc-theme/{theme}/bootswatch';"       
            scss_boot = f"@import '{sass_dir.value}/bootstrap-overrides.scss';"

            try:              
                with open(sass_dir.value + "/wvc-main.scss", "w") as main:
                    main.write(scss_var + "\n" + scss_boot + "\n" + scss_bootswatch + "\n")
                
                css_compressed = sass.compile(string=scss_var + "\n"+ scss_boot + "\n" + scss_bootswatch, output_style='compressed')
                with open("static/css/" + main_css, "w") as css:
                    css.write(css_compressed)    

                bootstrap_theme.value = theme
                bootstrap_theme.save()

                msg = _(f"Theme changed. Now: {theme}")
                messages.success(request, msg)
            except Exception as err:
                msg = err
                error_messages.append(msg)
            
            addlogmsg(request.user.username, "", msg)
            return HttpResponseRedirect(request.get_full_path())

        for setting in appsettings:
            if setting.key in request.POST:
                try:
                    setting.value = request.POST.get(setting.key, "")
                    setting.save()

                    msg = _(f"{setting.name} is changed. Now: {setting.value}")
                    messages.success(request, msg)
                except Exception as err:
                    msg = err
                    error_messages.append(msg)
                
                addlogmsg(request.user.username, "", msg)
                return HttpResponseRedirect(request.get_full_path())

    return render(request, 'appsettings.html', locals())

