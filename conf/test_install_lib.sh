#!/usr/bin/env bash
# Unit tests for conf/install-lib.sh. Run: bash conf/test_install_lib.sh
set -u
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/install-lib.sh"

fail=0
check() { if eval "$2"; then echo "ok - $1"; else echo "NOT ok - $1"; fail=1; fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# wvc_ensure_secret_key: creates, keeps, mode 600, regenerates when empty
wvc_ensure_secret_key "$tmp/data"
check "secret key created" "[ -s '$tmp/data/secret_key' ]"
check "secret key mode 600" "[ \"\$(stat -c %a '$tmp/data/secret_key')\" = 600 ]"
first="$(cat "$tmp/data/secret_key")"
wvc_ensure_secret_key "$tmp/data"
check "existing key kept" "[ \"\$(cat '$tmp/data/secret_key')\" = \"$first\" ]"
: > "$tmp/data/secret_key"   # truncate
wvc_ensure_secret_key "$tmp/data"
check "empty key regenerated" "[ -s '$tmp/data/secret_key' ]"
check "data dir is 700" "[ \"\$(stat -c %a '$tmp/data')\" = 700 ]"
rm "$tmp/data/secret_key"
check "fails when python cannot run" "! wvc_ensure_secret_key '$tmp/data' no-such-python 2>/dev/null"

# wvc_ensure_settings: creates once, keeps on re-run
echo "TEMPLATE" > "$tmp/tpl"
check "ensure_settings returns 0 on create" "wvc_ensure_settings '$tmp/tpl' '$tmp/settings.py'"
echo "EDITED" > "$tmp/settings.py"
check "ensure_settings returns 1 when present" "! wvc_ensure_settings '$tmp/tpl' '$tmp/settings.py'"
check "existing settings kept" "[ \"\$(cat '$tmp/settings.py')\" = EDITED ]"

# wvc_harden_modes
mkdir -p "$tmp/app/webvirtcloud" "$tmp/app/data"
echo x > "$tmp/app/webvirtcloud/settings.py"; echo x > "$tmp/app/db.sqlite3"
echo k > "$tmp/app/data/secret_key"
wvc_harden_modes "$tmp/app/webvirtcloud/settings.py" "$tmp/app/db.sqlite3" "$tmp/app/data"
check "settings 600" "[ \"\$(stat -c %a '$tmp/app/webvirtcloud/settings.py')\" = 600 ]"
check "db 600" "[ \"\$(stat -c %a '$tmp/app/db.sqlite3')\" = 600 ]"
check "data 700" "[ \"\$(stat -c %a '$tmp/app/data')\" = 700 ]"
check "secret 600" "[ \"\$(stat -c %a '$tmp/app/data/secret_key')\" = 600 ]"

# wvc_install_nginx: first run installs main + snippet, keeps backup; re-run keeps main
etc="$tmp/etc/nginx"; mkdir -p "$etc"
echo "ORIGINAL" > "$etc/nginx.conf"
echo "MAINTPL" > "$tmp/main_tpl"; echo "SNIPPET" > "$tmp/snippet"
wvc_install_nginx "$tmp/main_tpl" "$tmp/snippet" "$etc"
check "main replaced on first run" "[ \"\$(cat '$etc/nginx.conf')\" = MAINTPL ]"
check "original backed up" "[ \"\$(cat '$etc/nginx.conf.wvc-orig')\" = ORIGINAL ]"
check "snippet installed" "[ \"\$(cat '$etc/conf.d/webvirtcloud.conf')\" = SNIPPET ]"
echo "HANDEDITED" > "$etc/nginx.conf"
echo "SNIPPET2" > "$tmp/snippet"
wvc_install_nginx "$tmp/main_tpl" "$tmp/snippet" "$etc"
check "main NOT replaced on re-run" "[ \"\$(cat '$etc/nginx.conf')\" = HANDEDITED ]"
check "snippet refreshed on re-run" "[ \"\$(cat '$etc/conf.d/webvirtcloud.conf')\" = SNIPPET2 ]"

# fresh host: no existing main nginx.conf must not error
etc2="$tmp/etc2/nginx"; mkdir -p "$etc2"
wvc_install_nginx "$tmp/main_tpl" "$tmp/snippet" "$etc2"
check "fresh host installs main" "[ \"\$(cat '$etc2/nginx.conf')\" = MAINTPL ]"

# fresh host (no original config): a second run must NOT clobber operator edits
etc3="$tmp/etc3/nginx"; mkdir -p "$etc3"
wvc_install_nginx "$tmp/main_tpl" "$tmp/snippet" "$etc3"
echo "OP_EDIT" > "$etc3/nginx.conf"
wvc_install_nginx "$tmp/main_tpl" "$tmp/snippet" "$etc3"
check "no-orig second run keeps operator edit" "[ \"\$(cat '$etc3/nginx.conf')\" = OP_EDIT ]"

# wvc_allowed_hosts: fqdn + loopbacks + IPs, IPv6 bracketed, no duplicates
check "allowed hosts list" "[ \"\$(wvc_allowed_hosts wvc.example.com 192.0.2.10 2001:db8::1 127.0.0.1)\" = \"['wvc.example.com', 'localhost', '127.0.0.1', '[::1]', '192.0.2.10', '[2001:db8::1]']\" ]"
check "allowed hosts without ips" "[ \"\$(wvc_allowed_hosts wvc.example.com)\" = \"['wvc.example.com', 'localhost', '127.0.0.1', '[::1]']\" ]"

[ "$fail" = 0 ] && echo "ALL PASS" || echo "FAILURES"
exit "$fail"
