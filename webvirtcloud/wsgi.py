"""
WSGI config for webvirtcloud project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.7/howto/deployment/wsgi/
"""

execfile('/srv/webvirtcloud/venv/bin/activate_this.py', dict(__file__='/srv/webvirtcloud/venv/bin/activate_this.py'))

import os, sys
sys.path.append('/srv/webvirtcloud')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webvirtcloud.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
