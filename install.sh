#!/bin/bash
#
# WebVirtCloud Installer Bootstrap Script
# https://github.com/retspen/webvirtcloud
#

set -o pipefail

# Display help without requiring root privileges
for arg in "$@"; do
    if [ "$arg" = "-h" ] || [ "$arg" = "--help" ]; then
        echo "WebVirtCloud Installer Bootstrap"
        echo ""
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "OPTIONS:"
        echo "  -v, --verbose    Enable verbose installation output."
        echo "  -h, --help       Show this help message and exit."
        echo ""
        echo "Environment Variables:"
        echo "  WEBVIRTCLOUD_SCRIPT_URL    Custom URL to fetch webvirtcloud.sh installer"
        echo "  APP_REPO_URL               Custom WebVirtCloud git repository URL"
        exit 0
    fi
done

# Ensure script runs with root privileges
if [ "$(id -u)" != "0" ]; then
    SCRIPT_PATH="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/$(basename "$0")"
    if command -v sudo >/dev/null 2>&1; then
        exec sudo "$SCRIPT_PATH" "$@"
    elif command -v su >/dev/null 2>&1; then
        exec su -c "$SCRIPT_PATH $*"
    else
        echo "Error: Root privileges required, but neither 'sudo' nor 'su' was found." >&2
        exit 1
    fi
fi

# Locate existing webvirtcloud.sh or download it securely
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
TMP_DIR=""

# shellcheck disable=SC2329
cleanup() {
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT INT TERM

download_installer() {
    local url="$1"
    local dest="$2"
    echo "* Downloading webvirtcloud installer from $url..."

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 15 --retry 3 -o "$dest" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --timeout=15 --tries=3 -O "$dest" "$url"
    else
        echo "Error: Neither 'curl' nor 'wget' was found. Please install curl or wget." >&2
        exit 1
    fi
}

if [ -f "$SCRIPT_DIR/webvirtcloud.sh" ]; then
    INSTALLER="$SCRIPT_DIR/webvirtcloud.sh"
elif [ -f "./webvirtcloud.sh" ]; then
    INSTALLER="./webvirtcloud.sh"
else
    TMP_DIR="$(mktemp -d -t wvc-install.XXXXXX)"
    INSTALLER="$TMP_DIR/webvirtcloud.sh"
    UPSTREAM_URL="${WEBVIRTCLOUD_SCRIPT_URL:-https://raw.githubusercontent.com/retspen/webvirtcloud/master/webvirtcloud.sh}"
    download_installer "$UPSTREAM_URL" "$INSTALLER"
fi

# Ensure installer is executable
chmod 744 "$INSTALLER"

# Prepare log file location
LOG_FILE="/var/log/webvirtcloud-install.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
if ! touch "$LOG_FILE" 2>/dev/null; then
    LOG_FILE="/tmp/webvirtcloud-install.log"
fi

echo "* Executing installer ($INSTALLER)..."
echo "* Output is logged to $LOG_FILE"

# Execute installer and preserve exit status across pipe
"$INSTALLER" "$@" 2>&1 | tee -a "$LOG_FILE"
INSTALL_STATUS="${PIPESTATUS[0]}"

if [ "$INSTALL_STATUS" -ne 0 ]; then
    echo "" >&2
    echo "Error: WebVirtCloud installation failed with exit code $INSTALL_STATUS." >&2
    echo "See $LOG_FILE for details." >&2
    exit "$INSTALL_STATUS"
fi

exit 0
