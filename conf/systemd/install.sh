#!/bin/bash
FILEPATH=$(readlink -f "$0");
SCRIPTPATH=$(dirname "$FILEPATH");
cd "$SCRIPTPATH"
cp webvirt-* /lib/systemd/system/
cp webvirt /etc/default/
echo Run to start services \"systemctl daemon-reload\; systemctl enable --now $(ls webvirt-* | tr "\n" " ")\"
