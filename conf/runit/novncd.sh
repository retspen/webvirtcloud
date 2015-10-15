#!/bin/sh
# `/sbin/setuser www-data` runs the given command as the user `www-data`.
cd /srv/webvirtcloud
exec /sbin/setuser www-data /srv/webvirtcloud/venv/bin/python /srv/webvirtcloud/console/novncd >> /var/log/novncd.log 2>&1
