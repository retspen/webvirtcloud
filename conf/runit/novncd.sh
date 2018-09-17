#!/bin/sh

# `/sbin/setuser www-data` runs the given command as the user `www-data`.
RUNAS=`which setuser`
[ -z $RUNAS ] && RUNAS="`which sudo` -u"
USER=www-data

DJANGO_PROJECT=/srv/webvirtcloud
PYTHON=$DJANGO_PROJECT/venv/bin/python
NOVNCD=$DJANGO_PROJECT/console/novncd

# make novncd debug, verbose
#PARAMS="-d -v"

LOG=/var/log/novncd.log

cd $DJANGO_PROJECT
exec $RUNAS $USER $PYTHON $NOVNCD $PARAMS >> $LOG 2>&1
