#!/bin/bash
# Updates an installer or manual installation of WebVirtCloud to the newest
# master, as root:
#
#   (set -o pipefail &&
#    git -C /srv/webvirtcloud -c safe.directory=/srv/webvirtcloud fetch -q origin &&
#    git -C /srv/webvirtcloud -c safe.directory=/srv/webvirtcloud show origin/master:update.sh | bash)
#
# It runs the newest update.sh, also on an installation that has none yet.
# Nothing in the installation changes before its checks pass; then it stops the panel, backs it up
# into /root/webvirtcloud-backup-<date>, pulls, installs, migrates and starts
# the panel again. With PostgreSQL, back that database up first and pass
# --database-backed-up (... | bash -s -- --database-backed-up).
#
# The whole script is in main(): bash reads all of it before it runs, so the
# pull cannot change what runs; nothing in it reads the script piped in.

main() {
  set -o pipefail
  local app=${APP_PATH:-/srv/webvirtcloud} database_backed_up=false
  [ "${1:-}" = --database-backed-up ] && database_backed_up=true
  local units="webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker"
  local marker=$app/data/.update-backup  # a stopped update's backup: a run again resumes with it
  git() { command git -c safe.directory="$app" -C "$app" "$@"; }
  fail() { echo "update.sh: $*" >&2; exit 1; }

  # checks: nothing in the installation changes before they pass
  [ "$(id -u)" = 0 ] || fail "run it as root"
  [ -x "$app/venv/bin/python3" ] && [ -d "$app/.git" ] || fail "no installation in $app (set APP_PATH)"
  cd "$app" || fail "cannot enter $app"
  # the services' user and group: the installed unit's, else the owner of the panel's directory
  local user group
  user=$(systemctl show -P User webvirt-cloud 2>/dev/null)
  group=$(systemctl show -P Group webvirt-cloud 2>/dev/null)
  [ -n "$user" ] || user=$(stat -c %U "$app")
  [ -n "$group" ] || group=$user
  [ "$user" != root ] || fail "$app belongs to root: chown it to the panel's user first"
  # the services' environment: its database is the one to migrate
  if [ -f /etc/default/webvirtcloud ]; then
    set -a
    # shellcheck source=/dev/null
    . /etc/default/webvirtcloud
    set +a
  fi
  git fetch -q origin || fail "git fetch failed"
  local resume=""
  [ ! -f "$marker" ] || resume=$(cat "$marker")
  if [ -z "$resume" ]; then
    # an older version's own settings.py, not in the repository: its values go
    # into data/local_settings.py first, by hand (README, Local settings)
    if [ -f webvirtcloud/settings.py ] && ! git ls-files --error-unmatch webvirtcloud/settings.py >/dev/null 2>&1 &&
        [ ! -f data/local_settings.py ]; then
      echo "update.sh: this installation has its own webvirtcloud/settings.py. Put your own values" >&2
      echo "into $app/data/local_settings.py (README, Local settings), then run it again. Your" >&2
      echo "settings.py differs from its version's template in these lines (> yours):" >&2
      git show HEAD:webvirtcloud/settings.py.template | diff - webvirtcloud/settings.py >&2
      exit 1
    fi
    # tracked files changed by hand would stop the pull with the panel down; the ones
    # older versions changed themselves are put back below
    local edited
    edited=$(git status --porcelain --untracked-files=no | cut -c4- |
             grep -vE '^(static/|dev/scss/|install\.sh$|webvirtcloud\.sh$)')
    [ -z "$edited" ] || fail "these files of the repository were changed here; keep your changes elsewhere and undo them: $edited"
  fi
  # the database the panel uses, as its settings give it (the environment, settings.py and
  # local settings): the one backed up and migrated; a run that goes on reads it from the backup
  local loaded database
  if [ -n "$resume" ]; then
    database=$(cat "$resume/database") || fail "$resume/database is missing"
  else
    loaded=$(DJANGO_SETTINGS_MODULE=webvirtcloud.settings venv/bin/python3 -c 'from django.conf import settings
d = settings.DATABASES["default"]; print("DATABASE", d["ENGINE"].rsplit(".", 1)[-1], d["NAME"])' 2>&1)
    database=$(sed -n 's/^DATABASE //p' <<< "$loaded")
    [ -n "$database" ] || fail "the panel's settings do not load: $loaded"
  fi
  if [ "${database%% *}" != sqlite3 ] && ! $database_backed_up; then
    fail "the panel uses ${database%% *}: back that database up, then run it again with --database-backed-up"
  fi
  # root runs git in the repository, which belongs to the panel's user (the rollback steps too)
  command git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$app" ||
    command git config --global --add safe.directory "$app"

  local b old
  if [ -n "$resume" ]; then
    b=$resume
    echo "* Going on with the update that stopped; its backup is $b"
  else
    b=/root/webvirtcloud-backup-$(date +%Y%m%d-%H%M%S)
    mkdir -m 700 "$b" && git rev-parse HEAD > "$b/commit" && echo "$database" > "$b/database" && echo "$b" > "$marker" ||
      fail "cannot make the backup directory $b"
  fi
  old=$(cat "$b/commit")
  echo "* Stopping the panel"
  # shellcheck disable=SC2086
  systemctl stop $units
  # shellcheck disable=SC2086
  ! systemctl is-active --quiet $units || fail "the panel did not stop"

  if [ -z "$resume" ]; then
    echo "* Backing up into $b"
    if ! (
      set -e
      if [ "${database%% *}" = sqlite3 ]; then
        venv/bin/python3 -c "import sqlite3,sys; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect(sys.argv[2]))" \
          "${database#* }" "$b/db.sqlite3.part"
        mv "$b/db.sqlite3.part" "$b/db.sqlite3"
      fi
      for file in data/local_settings.py /etc/nginx/conf.d/webvirtcloud.conf /etc/default/webvirtcloud; do
        [ ! -f "$file" ] || cp -p "$file" "$b"/
      done
    ); then
      rm -f "$marker"
      # shellcheck disable=SC2086
      systemctl start $units
      fail "the backup into $b failed; nothing was changed and the panel was started again"
    fi
    # what older versions left in the checkout: their own settings.py (git pull now
    # brings settings.py), migrations an old installer generated (archived whole,
    # then removed), static files they collected into the tracked static/, and
    # install.sh and webvirtcloud.sh they deleted
    if [ -f webvirtcloud/settings.py ] && ! git ls-files --error-unmatch webvirtcloud/settings.py >/dev/null 2>&1; then
      mv webvirtcloud/settings.py "$b"/ || fail "cannot move the old settings.py; the panel is stopped, the backup is $b"
    fi
    git ls-files -z --others --exclude-standard -- '*/migrations/*.py' > "$b/local-migrations.list" &&
      tar --null -T "$b/local-migrations.list" -cf "$b/local-migrations.tar" &&
      xargs -0 -r rm -f < "$b/local-migrations.list" && rm "$b/local-migrations.list" ||
      fail "cannot keep the generated migrations; the panel is stopped, the backup is $b"
    local changed
    changed=$(git ls-files -m -- static dev/scss install.sh webvirtcloud.sh)
    # shellcheck disable=SC2086
    [ -z "$changed" ] || git checkout -- $changed ||
      fail "cannot restore the tracked files older versions changed; the panel is stopped, the backup is $b"
  fi

  echo "* Pulling"
  git checkout -q master && git pull -q --ff-only || fail "git pull failed; the panel is stopped, the backup is $b"

  echo "* Installing, migrating"
  venv/bin/pip3 install -q -U -r conf/requirements.txt || fail "pip failed; the panel is stopped, the backup is $b"
  if venv/bin/pip3 show -q django-auth-ldap >/dev/null 2>&1; then
    venv/bin/pip3 install -q -U -r conf/requirements-ldap.txt || fail "pip (LDAP) failed; the panel is stopped, the backup is $b"
  fi
  # an old installer's migration has the name of a tracked one, which migrate would skip
  if tar -tf "$b/local-migrations.tar" | grep -qx accounts/migrations/0006_alter_userattributes_id_alter_userinstance_id_and_more.py; then
    venv/bin/python3 manage.py migrate accounts 0005 --fake || fail "migrate failed; the panel is stopped, the backup is $b"
  fi
  venv/bin/python3 manage.py migrate || fail "migrate failed; the panel is stopped, the backup is $b"
  venv/bin/python3 manage.py collectstatic --noinput -v 0 || fail "collectstatic failed; the panel is stopped, the backup is $b"
  chown -R "$user:$group" "$app" && chmod -R go-rwx data && { [ ! -f db.sqlite3 ] || chmod 600 db.sqlite3; } ||
    fail "cannot set the files' owner; the panel is stopped, the backup is $b"

  echo "* Starting the panel"
  local unit
  for unit in $units webvirt-backup; do
    sed -e "s/^User=.*/User=$user/" -e "s/^Group=.*/Group=$group/" -e "s#/srv/webvirtcloud#$app#g" \
      "conf/systemd/$unit.service" > "/etc/systemd/system/.$unit.service" &&
      mv "/etc/systemd/system/.$unit.service" "/etc/systemd/system/$unit.service" ||
      fail "cannot install $unit.service; the panel is stopped, the backup is $b"
  done
  cp conf/systemd/webvirt-backup.timer /etc/systemd/system/ || fail "cannot install webvirt-backup.timer"
  # shellcheck disable=SC2086
  systemctl daemon-reload && systemctl enable --now -q $units webvirt-backup.timer ||
    fail "the panel did not start: journalctl -u webvirt-cloud; the backup is $b"
  rm -f "$marker"
  nginx -t -q && systemctl reload nginx || fail "nginx refused its config; the panel runs, nginx was not reloaded"

  # the nginx config holds this installation's own lines (server_name, TLS): it is
  # not replaced; what the new version changes in it is shown to be applied by hand
  git diff --quiet "$old" HEAD -- conf/nginx/webvirtcloud.conf
  case $? in
    0) ;;
    1) echo "* The nginx config of this version changed; apply this to /etc/nginx/conf.d/webvirtcloud.conf,"
       echo "  then: nginx -t && systemctl reload nginx"
       git diff "$old" HEAD -- conf/nginx/webvirtcloud.conf ;;
    *) echo "* Compare /etc/nginx/conf.d/webvirtcloud.conf with $app/conf/nginx/webvirtcloud.conf by hand." ;;
  esac
  echo "* Updated from ${old:0:8} to $(git rev-parse --short=8 HEAD); the backup is $b"
}

main "$@" < /dev/null
exit
