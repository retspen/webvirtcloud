#!/usr/bin/env bash
# Idempotent installer primitives. Sourcing this file has NO side effects;
# it only defines functions, so it can be unit-tested (webvirtcloud/tests/sh/install_lib.test.sh).

# Create <data_dir>/secret_key (mode 600) only if missing or empty; keep an
# existing key. A blank key would make Django fail to boot, so an empty file is
# treated as missing, and the function fails when it could not write one.
wvc_ensure_secret_key() {
  local data_dir="$1" python="${2:-python3}" key_file
  key_file="$data_dir/secret_key"
  mkdir -p "$data_dir"
  chmod 700 "$data_dir"
  if [ ! -s "$key_file" ]; then
    # umask 077 so the key is never group/world readable, even briefly
    ( umask 077; "$python" -c 'import secrets; print(secrets.token_urlsafe(50))' > "$key_file" )
  fi
  chmod 600 "$key_file"
  # an empty key means the python did not run: the panel would not start
  [ -s "$key_file" ]
}

# Copy settings.py from the template only when it does not already exist, so a
# re-run never overwrites local edits. 0 + "created" on first copy; 1 + "kept"
# when it already exists.
wvc_ensure_settings() {
  local template="$1" target="$2"
  if [ -f "$target" ]; then
    echo "kept"
    return 1
  fi
  cp "$template" "$target"
  echo "created"
  return 0
}

# Restrict modes so the secret, settings, and db are not world-readable.
wvc_harden_modes() {
  local settings="$1" db="$2" data_dir="$3"
  [ -e "$settings" ] && chmod 600 "$settings"
  [ -e "$db" ] && chmod 600 "$db"
  [ -d "$data_dir" ] && chmod 700 "$data_dir"
  [ -e "$data_dir/secret_key" ] && chmod 600 "$data_dir/secret_key"
  return 0
}

# Install the nginx main config only on first run (keeping a one-time backup of
# whatever was there), and always refresh the app's conf.d snippet. A re-run
# therefore never clobbers an operator's edited main nginx.conf.
wvc_install_nginx() {
  local main_template="$1" snippet="$2" etc="$3" marker
  marker="$etc/.wvc-nginx-installed"
  mkdir -p "$etc/conf.d"
  # Use a dedicated marker (always created on first install) rather than the
  # backup file, which is absent when the host had no nginx.conf to begin with.
  if [ ! -f "$marker" ]; then
    [ -f "$etc/nginx.conf" ] && cp "$etc/nginx.conf" "$etc/nginx.conf.wvc-orig"
    cp "$main_template" "$etc/nginx.conf"
    : > "$marker"
  fi
  cp "$snippet" "$etc/conf.d/webvirtcloud.conf"
  return 0
}

# Python list literal for ALLOWED_HOSTS: the FQDN, the loopbacks and the given
# IPs. IPv6 addresses are bracketed, as Django compares them.
wvc_allowed_hosts() {
  local host out="" seen=" "
  for host in "$1" localhost 127.0.0.1 ::1 "${@:2}"; do
    case "$host" in *:*) host="[$host]" ;; esac
    case "$seen" in *" $host "*) continue ;; esac
    seen+="$host "
    out+="${out:+, }'$host'"
  done
  echo "[$out]"
}
