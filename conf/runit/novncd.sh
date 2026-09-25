#!/bin/sh

USER="www-data"
DJANGO_PROJECT="/srv/webvirtcloud"
PYTHON="$DJANGO_PROJECT/venv/bin/python3"
NOVNCD="$DJANGO_PROJECT/console/novncd"
LOG="/var/log/novncd.log"

cd "$DJANGO_PROJECT" || exit 1

# make novncd debug, verbose
#PARAMS="-d -v"

if [ -x /sbin/setuser ]; then
    if [ -n "$PARAMS" ]; then
        # shellcheck disable=SC2086
        exec /sbin/setuser "$USER" "$PYTHON" "$NOVNCD" $PARAMS >> "$LOG" 2>&1
    else
        exec /sbin/setuser "$USER" "$PYTHON" "$NOVNCD" >> "$LOG" 2>&1
    fi
elif command -v su >/dev/null 2>&1; then
    if [ -n "$PARAMS" ]; then
        # shellcheck disable=SC2086
        exec su -s /bin/sh "$USER" -c "exec \"$PYTHON\" \"$NOVNCD\" $PARAMS" >> "$LOG" 2>&1
    else
        exec su -s /bin/sh "$USER" -c "exec \"$PYTHON\" \"$NOVNCD\"" >> "$LOG" 2>&1
    fi
fi
