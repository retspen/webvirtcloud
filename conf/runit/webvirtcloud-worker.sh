#!/bin/sh
# The job worker (one per installation). runit stops it with TERM; it drains
# running jobs for 60 s and exits by itself.
cd /srv/webvirtcloud || exit
export WEBVIRTCLOUD_LOG_FILE=/srv/webvirtcloud/data/webvirtcloud-worker.log
# its output goes to the container's output (docker logs)
exec /sbin/setuser www-data /srv/webvirtcloud/venv/bin/python3 manage.py run_worker 2>&1
