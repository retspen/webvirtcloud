#!/bin/bash

# ensure running as root
if [ "$(id -u)" != "0" ]; then
    #Debian doesnt have sudo if root has a password.
    if ! hash sudo 2>/dev/null; then
        exec su -c "$0" "$@"
    else
        exec sudo "$0" "$@"
    fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/webvirtcloud.sh" ]; then
    INSTALLER="$SCRIPT_DIR/webvirtcloud.sh"
elif [ -f "./webvirtcloud.sh" ]; then
    INSTALLER="./webvirtcloud.sh"
else
    INSTALLER="./webvirtcloud.sh"
    wget -O "$INSTALLER" "${WEBVIRTCLOUD_SCRIPT_URL:-https://raw.githubusercontent.com/catborise/webvirtcloud/master/webvirtcloud.sh}"
fi

chmod 744 "$INSTALLER"
"$INSTALLER" "$@" 2>&1 | tee -a /var/log/webvirtcloud-install.log