#!/bin/sh
# `/sbin/setuser www-data` runs the given command as the user `www-data`.
cd /srv/webvirtcloud || exit
exec /sbin/setuser www-data /srv/webvirtcloud/venv/bin/gunicorn webvirtcloud.wsgi:application -c /srv/webvirtcloud/gunicorn.conf.py >> /var/log/webvirtcloud.log 2>&1
