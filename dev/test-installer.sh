#!/bin/bash
# Installs the panel with install.sh in a systemd container of one distribution
# and checks that it answers: its services run, it has a secret key, an admin
# password and its local settings, and the login page loads. It installs the
# committed HEAD.
#
# Usage, from the repository root (needs docker):
#   dev/test-installer.sh IMAGE      e.g. debian:13, almalinux:10, opensuse/leap:15.6
set -euo pipefail

image=${1:?usage: dev/test-installer.sh IMAGE}
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

# the installer clones the repository: a clone of HEAD (root in the container reads it)
git clone -q --no-hardlinks . "$repo/webvirtcloud"

docker build -q -t "$name" - > /dev/null <<EOF
FROM $image
RUN $prepare
CMD ["/usr/lib/systemd/systemd"]
EOF
docker run -d --name "$name" --privileged --cgroupns=private --tmpfs /run --tmpfs /run/lock \
  -v "$repo/webvirtcloud:/repo:ro" "$name" > /dev/null

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
  mkdir -p /root/inst && cp /repo/install.sh /repo/webvirtcloud.sh /root/inst/
  cd /root/inst && printf "n\n\n" | APP_REPO_URL=/repo ./install.sh' ||
  { docker exec "$name" tail -n 50 /var/log/webvirtcloud-install.log; exit 1; }

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
echo "$image: installed, the login page and its stylesheet load"
