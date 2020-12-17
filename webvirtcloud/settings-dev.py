"""
Django dev settings for webvirtcloud project.

HowTo: python3 manage.py runserver 0:8000 --settings=webvirtcloud.settings-dev

"""

from webvirtcloud.settings import *

DEBUG = True
TEMPLATE_DEBUG = True


INSTALLED_APPS += [
    "debug_toolbar",
]

MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]

# DebugToolBar
INTERNAL_IPS = ("127.0.0.1",)
DEBUG_TOOLBAR_CONFIG = {
    "INTERCEPT_REDIRECTS": False,
}
