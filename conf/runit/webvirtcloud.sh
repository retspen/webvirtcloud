#!/bin/sh
# `/sbin/setuser www-data` runs the given command as the user `www-data`.
cd /srv/webvirtcloud || exit
# gunicorn's own and access log go to the container's output (docker logs)
exec /sbin/setuser www-data /srv/webvirtcloud/venv/bin/gunicorn webvirtcloud.wsgi:application -c /srv/webvirtcloud/gunicorn.conf.py 2>&1
