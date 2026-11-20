#!/bin/bash
# Installs the panel with install.sh in a systemd container of one distribution
# and checks that it answers: its services run, it has a secret key, an admin
# password and its local settings, and the login page loads. It installs the
# committed HEAD; with FROM, it installs that version and updates it to HEAD
# with update.sh.
#
# Usage, from the repository root (needs docker):
#   dev/test-installer.sh IMAGE [FROM]    e.g. debian:13, almalinux:10 v4.3.0
set -euo pipefail

image=${1:?usage: dev/test-installer.sh IMAGE [FROM]}
from=${2:-}
case $image in
  ubuntu:* | debian:*) prepare="apt-get update && apt-get install -y systemd systemd-sysv" ;;
  almalinux:* | */openeuler:*) prepare="dnf -y install systemd findutils" ;;
  opensuse/*) prepare="zypper -n install systemd" ;;
  *) echo "No container recipe for $image" >&2; exit 2 ;;
esac

repo=$(mktemp -d)
# unique: runs on one docker do not remove each other's container
name=wvc-installer-test-$(tr -c 'a-z0-9' '-' <<< "$image" | sed 's/-*$//')-${repo##*.}
name=${name,,}
cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker rmi "$name" >/dev/null 2>&1 || true
  rm -rf "${repo:?}"
}
trap cleanup EXIT

# the installer clones the repository: a clone of HEAD as master (root in the
# container reads it), and of FROM for an update
git clone -q --no-hardlinks . "$repo/webvirtcloud"
git -C "$repo/webvirtcloud" checkout -q -B master
installed=$repo/webvirtcloud
if [ -n "$from" ]; then
  git clone -q --no-hardlinks . "$repo/from"
  git -C "$repo/from" checkout -q -B master "$from"
  installed=$repo/from
fi

docker build -q -t "$name" - > /dev/null <<EOF
FROM $image
RUN $prepare
CMD ["/usr/lib/systemd/systemd"]
EOF
docker run -d --name "$name" --privileged --cgroupns=private --tmpfs /run --tmpfs /run/lock \
  -v "$repo/webvirtcloud:/repo:ro" -v "$installed:/installed:ro" "$name" > /dev/null

for _ in $(seq 60); do
  state=$(docker exec "$name" systemctl is-system-running 2>/dev/null || true)
  [[ $state == running || $state == degraded ]] && break
  sleep 1
done
[[ $state == running || $state == degraded ]] || { echo "systemd did not start: $state"; docker logs "$name"; exit 1; }

# the answers: no FQDN for nginx, the default noVNC port
docker exec "$name" bash -c '
  # git comes with the installer; the mounted clone is not root'"'"'s
  printf "[safe]\n\tdirectory = *\n" >> /etc/gitconfig
  mkdir -p /root/inst && cp /installed/install.sh /installed/webvirtcloud.sh /root/inst/
  cd /root/inst && printf "n\n\n" | APP_REPO_URL=/installed ./install.sh' ||
  { docker exec "$name" tail -n 50 /var/log/webvirtcloud-install.log; exit 1; }

if [ -n "$from" ]; then
  # the README's update command, from HEAD as the origin's master
  docker exec "$name" bash -e -c '
    update() {
      (set -o pipefail &&
       git -C /srv/webvirtcloud fetch -q origin && git -C /srv/webvirtcloud show origin/master:update.sh | bash)
    }
    git -C /srv/webvirtcloud remote set-url origin /repo
    if [ -f /srv/webvirtcloud/webvirtcloud/settings.py ] && [ ! -f /srv/webvirtcloud/data/local_settings.py ]; then
      # an older version'"'"'s own settings.py: it stops before changing anything ...
      commit=$(git -C /srv/webvirtcloud rev-parse HEAD)
      if update 2>/root/refused; then echo "update.sh did not refuse"; exit 1; fi
      grep -q "has its own webvirtcloud/settings.py" /root/refused
      systemctl is-active --quiet webvirt-cloud
      [ "$(git -C /srv/webvirtcloud rev-parse HEAD)" = "$commit" ]
      if ls -d /root/webvirtcloud-backup-* >/dev/null 2>&1; then echo "a refused update made a backup"; exit 1; fi
      # ... until the operator moved its values into the local file
      grep -E "^(TIME_ZONE|WS_PORT|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS) = " /srv/webvirtcloud/webvirtcloud/settings.py \
        > /srv/webvirtcloud/data/local_settings.py
    fi
    # a failure after the backup (pip): run again, it goes on with that backup
    old=$(git -C /srv/webvirtcloud rev-parse HEAD)
    chmod -x /srv/webvirtcloud/venv/bin/pip3
    if update; then echo "update.sh did not stop at pip"; exit 1; fi
    chmod +x /srv/webvirtcloud/venv/bin/pip3
    update
    [ "$(ls -d /root/webvirtcloud-backup-* | wc -l)" = 1 ]
    [ "$(cat /root/webvirtcloud-backup-*/commit)" = "$old" ]
    [ "$(git -C /srv/webvirtcloud rev-parse HEAD)" = "$(git -C /repo rev-parse HEAD)" ]
    update  # once more, with nothing new: it runs again as safely'
fi

docker exec "$name" bash -e -c '
  test -s /srv/webvirtcloud/data/secret_key || { echo "No secret key"; exit 1; }
  test -s /srv/webvirtcloud/data/admin_password || { echo "No admin password"; exit 1; }
  test -s /srv/webvirtcloud/data/local_settings.py || { echo "No local settings"; exit 1; }
  # curl is not on every distribution; the panel'"'"'s Python is
  /srv/webvirtcloud/venv/bin/python3 - <<PY
import re, time, urllib.request
page = ""
for _ in range(30):
    try:
        page = urllib.request.urlopen("http://127.0.0.1/accounts/login/", timeout=5).read().decode()
    except OSError:
        pass
    # the panel'"'"'s login form, not a page nginx serves instead
    if "id=\"form-signin\"" in page:
        break
    time.sleep(1)
else:
    raise SystemExit("The login page does not load")
# a stylesheet it links, as nginx serves the static files
stylesheet = re.search(r"href=\"(/static/[^\"]+[.]css)\"", page).group(1)
urllib.request.urlopen("http://127.0.0.1" + stylesheet, timeout=5)
PY
  # after the page: a daemon that died meanwhile is seen
  for unit in webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker nginx; do
    systemctl is-active --quiet "$unit" || { systemctl status "$unit" --no-pager; exit 1; }
  done'
echo "$image: ${from:+$from updated to HEAD, }installed, the login page and its stylesheet load"
