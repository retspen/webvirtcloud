"""
Django dev settings for webvirtcloud project.

HowTo: python3 manage.py runserver 0:8000 --settings=webvirtcloud.settings-dev --nostatic

"""

from webvirtcloud.settings import *

DEBUG = True
TEMPLATE_DEBUG = True


INSTALLED_APPS += [
    "debug_toolbar",
    "template_profiler_panel",
]

MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]

# DebugToolBar
INTERNAL_IPS = ("127.0.0.1",)
DEBUG_TOOLBAR_CONFIG = {
    "INTERCEPT_REDIRECTS": False,
}
# http://django-debug-toolbar.readthedocs.org/en/latest/configuration.html#debug-toolbar-panels
DEBUG_TOOLBAR_PANELS = [
    'debug_toolbar.panels.history.HistoryPanel',
    'debug_toolbar.panels.versions.VersionsPanel',
    'debug_toolbar.panels.timer.TimerPanel',
    'debug_toolbar.panels.settings.SettingsPanel',
    'debug_toolbar.panels.headers.HeadersPanel',
    'debug_toolbar.panels.request.RequestPanel',
    'debug_toolbar.panels.sql.SQLPanel',
    'debug_toolbar.panels.staticfiles.StaticFilesPanel',
    'debug_toolbar.panels.templates.TemplatesPanel',
    'debug_toolbar.panels.cache.CachePanel',
    'debug_toolbar.panels.signals.SignalsPanel',
    'debug_toolbar.panels.redirects.RedirectsPanel',
    'debug_toolbar.panels.profiling.ProfilingPanel',
    'template_profiler_panel.panels.template.TemplateProfilerPanel',
]
