"""
WSGI config for webvirtcloud project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/wsgi/
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

# execfile('/srv/webvirtcloud/venv/bin/activate_this.py', dict(__file__='/srv/webvirtcloud/venv/bin/activate_this.py'))
exec(
    compile(
        open("/srv/webvirtcloud/venv/bin/activate", "rb").read(),
        "/srv/webvirtcloud/venv/bin/activate",
        "exec",
    )
)

sys.path.append("/srv/webvirtcloud")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webvirtcloud.settings")

application = get_wsgi_application()
