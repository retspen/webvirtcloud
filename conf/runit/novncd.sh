#!/bin/sh

cd /srv/webvirtcloud || exit 1
# its log goes to the container's output (docker logs)
exec /sbin/setuser www-data /srv/webvirtcloud/venv/bin/python3 /srv/webvirtcloud/console/novncd 2>&1
