#!/bin/sh
# Copies the panel's backups to an off-site restic repository; run as root by
# webvirt-offsite.service with the settings of /etc/webvirtcloud-offsite.env.
set -eu
newest=$(find "$WVC_BACKUPS" -maxdepth 1 -name 'webvirtcloud-backup-*' -mmin -1560)
if [ -z "$newest" ]; then
    echo "No backup from the last 26 hours in $WVC_BACKUPS: is the panel's backup running?" >&2
    exit 1
fi
# dot files are the lock and the backup being written
restic backup --tag webvirtcloud --exclude '.*' "$WVC_BACKUPS"
restic forget --tag webvirtcloud --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
if [ -n "${WVC_HEARTBEAT:-}" ]; then
    curl -fsS -m 10 --retry 3 -o /dev/null "$WVC_HEARTBEAT"
fi
