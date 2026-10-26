#!/bin/sh
# The serial console daemon; it refuses connections while SERIAL_CONSOLE_ENABLED is off.

cd /srv/webvirtcloud || exit 1
# its log goes to the container's output (docker logs)
exec /sbin/setuser www-data /srv/webvirtcloud/venv/bin/python3 /srv/webvirtcloud/console/socketiod 2>&1
