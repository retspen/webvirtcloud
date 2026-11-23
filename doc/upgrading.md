# Updating

- Update: [Docker](#docker) or [installer and manual installation](#installer-and-manual-installation)
- [Restore and rollback](#restore-and-rollback)
- [Moving to a new machine](#moving-to-a-new-machine)
- [Behavior changes](behavior-changes.md): what an update changes for operators and users

Every update first backs the panel up into a directory of its own (mode 700, named by date): the database, the commit it was taken from and the files the update could change. The database is copied with SQLite's backup API, which also finishes a write interrupted by a crash. This covers sqlite only; with PostgreSQL (`WEBVIRTCLOUD_DB_HOST`), back up that database yourself before updating.

## Docker

Each new container runs the migrations at start; the database, the secret key and [`data/local_settings.py`](configuration.md#local-settings) stay in the `webvirtcloud-data` volume. Keep your environment in `docker-compose.override.yml` (at least `ALLOWED_HOSTS`, see [Docker](install.md#docker)). An override that mounts your own `settings.py` (`./settings.py:/srv/webvirtcloud/webvirtcloud/settings.py`, as the README of older versions said) would keep that old file: remove the mount and move your own values into `data/local_settings.py`.

Run the commands in the directory you installed from. Compose names the deployment after that directory (`webvirtcloud`), so another clone in a directory of the same name acts on the same containers and volumes.

```bash
cd webvirtcloud &&
b=../webvirtcloud-backup-$(date +%Y%m%d-%H%M%S) &&
mkdir -m 700 "$b" && git rev-parse HEAD > "$b/commit" &&
git checkout master && git pull &&
docker compose build &&
docker compose stop -t 95 &&
{ docker compose cp webvirtcloud:/var/www/.pki "$b/pki" || mkdir -m 700 "$b/pki"; } &&
docker compose run --rm --no-deps -T --entrypoint /srv/webvirtcloud/venv/bin/python3 webvirtcloud \
  -c "import sqlite3,sys,tempfile; t=tempfile.mktemp(); sqlite3.connect('data/db.sqlite3').backup(sqlite3.connect(t)); sys.stdout.buffer.write(open(t,'rb').read())" > "$b/db.sqlite3.part" &&
mv "$b/db.sqlite3.part" "$b/db.sqlite3" &&
docker compose up -d --no-start &&
docker compose cp "$b/pki/." webvirtcloud:/var/www/.pki/ &&
docker compose start
```

The TLS client certificates (`/var/www/.pki`) go into the backup and back into the new container before it starts: up to v4.3.0 they were in the container itself, not in a volume. A container of v4.3.0 or older without them may have no `.pki`: `docker compose cp` then says it cannot find it, and the `mkdir` stands in.

## Moving from supervisor to systemd

Versions up to v3.0.0 ran the panel under supervisor. Once, before the update below, stop it there, keep its config and remove it:

```bash
supervisorctl stop webvirtcloud novncd socketiod webvirt-worker
mv /etc/supervisor/conf.d/webvirtcloud.conf /root/webvirtcloud-supervisor.conf   # Debian / Ubuntu
mv /etc/supervisord.d/webvirtcloud.ini /root/webvirtcloud-supervisor.conf        # RHEL / openSUSE
supervisorctl update
```

Move the `environment=` values of that config into `/etc/default/webvirtcloud` (root, mode 600), one `NAME='value'` per line; leave out the worker's `WEBVIRTCLOUD_LOG_FILE`. The update installs and starts the systemd units. Remove supervisor once nothing else uses it.

On each compute that ran gstfsd under supervisor, remove its program (`/etc/supervisor/conf.d/gstfsd.conf` on Debian / Ubuntu, `/etc/supervisord.d/gstfsd.ini` on RHEL / openSUSE), run `sudo supervisorctl update`, install gstfsd as in [Adding a Compute Node, step 3](compute-nodes.md#3-install-gstfsd), and remove supervisor once nothing else uses it.

## Installer and manual installation

From a root shell:

```bash
(set -o pipefail &&
 git -C /srv/webvirtcloud -c safe.directory=/srv/webvirtcloud fetch -q origin &&
 git -C /srv/webvirtcloud -c safe.directory=/srv/webvirtcloud show origin/master:update.sh | bash)
```

- It runs the newest `update.sh` of the repository, also on an installation that has none yet. Another directory than `/srv/webvirtcloud`: set it in the command and `APP_PATH` for `bash`; the units get it.
- Nothing in the installation changes until its checks pass; files of the repository changed by hand stop it, listed. With PostgreSQL (the database Django is set up with), back that database up first and run it with `... | bash -s -- --database-backed-up`.
- An installation of an older version has its own `webvirtcloud/settings.py`: it stops and lists the lines that differ from that version's template: your own. Put your own values into [`data/local_settings.py`](configuration.md#local-settings) and run it again:
  - Typical ones are `TIME_ZONE`, `WS_PORT`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and LDAP.
  - **With PostgreSQL, your `DATABASES`:** the default is sqlite, so without it `migrate` would make a new, empty sqlite database and the panel would start on that.
  - A literal `SECRET_KEY = "..."` (older installers wrote it there) goes into `data/secret_key` instead (with no key every page fails, with another every user is signed out).
  - Keep `SHOW_PROFILE_EDIT_PASSWORD` for this one update if you have it (migration `accounts.0008` reads it), then delete it.
- It stops the panel and backs it up into `/root/webvirtcloud-backup-<date>`: the database, the commit, `data/local_settings.py`, the nginx config, `/etc/default/webvirtcloud`, an older version's own `settings.py` and the migrations an old installer generated (`local-migrations.tar`). Then it pulls `master`, installs the requirements (the LDAP ones too if installed), migrates, collects the static files, gives the files to the panel's user (the owner of `/srv/webvirtcloud`), installs the systemd units and starts the panel.
- It does not replace `/etc/nginx/conf.d/webvirtcloud.conf`, which holds your `server_name`, TLS and noVNC port: when the new version changes that config, it prints the change to apply by hand.
- A failure stops it with the reason and the backup's directory. A failed backup starts the panel again; a later failure before the panel starts leaves it stopped until the cause is fixed and the command runs again, which goes on with that backup, or it is [rolled back](#restore-and-rollback). An nginx config nginx refuses stops it after the panel started: fix it and `systemctl reload nginx`.
- Older versions collected static files into `static/`; `git clean -n static/` lists the leftovers, which can be deleted.

## Restore and rollback

Restoring puts back the database as it was at the backup; changes made since are lost. Migrations are not reversed. This covers sqlite; restore a PostgreSQL database from your own backup before rolling back the code. Set `b` to the backup directory to restore. To restore the database without rolling back the code, leave out the `build` line and every line that takes another file from `$b`: the commit, `local-migrations.tar`, `settings.py` and `local_settings.py`, the nginx config and `/etc/default/webvirtcloud`.

Docker, in the directory you installed from:

```bash
cd webvirtcloud &&
b=../webvirtcloud-backup-YYYYMMDD-HHMMSS &&
docker compose stop -t 95 &&
docker compose run --rm --no-deps -T --entrypoint /srv/webvirtcloud/venv/bin/python3 webvirtcloud \
  -c "import os,sqlite3,sys,tempfile; t=tempfile.mktemp(); open(t,'wb').write(sys.stdin.buffer.read()); [os.remove(p) for p in ('data/db.sqlite3-journal','data/db.sqlite3-wal','data/db.sqlite3-shm') if os.path.exists(p)]; sqlite3.connect(t).backup(sqlite3.connect('data/db.sqlite3'))" < "$b/db.sqlite3" &&
git checkout "$(cat "$b/commit")" &&
docker compose build &&
docker compose up -d --no-start &&
{ [ ! -d "$b/pki" ] || docker compose cp "$b/pki/." webvirtcloud:/var/www/.pki/; } &&
docker compose start &&
docker compose exec webvirtcloud chown -R www-data:www-data /var/www/.pki
```

A version from before `data/local_settings.py` builds its `settings.py` from a template and does not read that file: to roll back to one, mount your `settings.py` again as that version's README says. The container fixes the ownership and modes of the database and keys at start; the last line gives the TLS client certificates to `www-data` also in an image of v4.3.0 or older, which neither does that nor keeps them in a volume.

Installer and manual installation, from a root shell (`nginx:nginx` on RHEL / openSUSE):

```bash
b=/root/webvirtcloud-backup-YYYYMMDD-HHMMSS
systemctl stop webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
cd /srv/webvirtcloud &&
! systemctl is-active --quiet webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker &&
git checkout -- $(git ls-files -m -- static/css dev/scss) &&
git checkout "$(cat "$b/commit")" &&
{ [ ! -f "$b/local-migrations.tar" ] || tar -xf "$b/local-migrations.tar"; } &&
venv/bin/python3 -c "import os,sqlite3,sys; [os.remove(p) for p in ('db.sqlite3-journal','db.sqlite3-wal','db.sqlite3-shm') if os.path.exists(p)]; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect('db.sqlite3'))" "$b/db.sqlite3" &&
{ [ ! -f "$b/settings.py" ] || cp "$b/settings.py" webvirtcloud/settings.py; } &&
{ [ ! -f "$b/local_settings.py" ] || cp -p "$b/local_settings.py" data/; } &&
{ [ ! -f "$b/webvirtcloud.conf" ] || cp "$b/webvirtcloud.conf" /etc/nginx/conf.d/webvirtcloud.conf; } &&
{ [ ! -f "$b/webvirtcloud" ] || { set -a; . "$b/webvirtcloud"; set +a; }; } &&
venv/bin/pip3 install -r conf/requirements.txt &&
venv/bin/python3 manage.py migrate &&
venv/bin/python3 manage.py collectstatic --noinput &&
chown -R www-data:www-data /srv/webvirtcloud &&
chmod 600 db.sqlite3 && { [ ! -f "$b/settings.py" ] || chmod 600 webvirtcloud/settings.py; } &&
rm -f data/.update-backup
```

A backup of a version that had its own `settings.py` (not in the repository) holds that file: the steps put it back for the older code.

Put back `/etc/default/webvirtcloud` if the backup has it (`cp -p "$b/webvirtcloud" /etc/default/`), then reload nginx and start the panel:

```bash
nginx -t && systemctl reload nginx && systemctl start webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
```

A version from before v3.0.0 has no worker: `systemctl disable --now webvirt-worker`. A rollback keeps the systemd units, and drops what a stopped `update.sh` kept to go on with (`data/.update-backup`). A rollback leaves the clone on a detached HEAD at the restored commit; `update.sh` records that commit before it switches back to `master`.

## Moving to a new machine

A [backup](backups.md) moves the panel to a new machine, or back onto lost volumes: the database, the secret key (signed-in users stay signed in), the worker's id and the SSH keys and TLS certificates the computes accept. Install the panel there first, the same version or a newer one, then copy the backup directory over and set `b` to it. The backup does not hold `docker-compose.override.yml`, the nginx config or `/etc/default/webvirtcloud`: bring your own lines over yourself. Users sign in with their passwords from the backup; the new installation's `data/admin_password` no longer applies. The backup's `secret_key` is the key in use, also one set as `SECRET_KEY` in the environment. With PostgreSQL, restore that database yourself and leave out the line below that restores `db.sqlite3` (the backup has none), and stop the old panel before the new one starts: both would run the jobs of the one database.

Docker, in the directory you installed from:

```bash
cd webvirtcloud &&
b=../webvirtcloud-backup-YYYYMMDD-HHMMSS &&
docker compose stop -t 95 &&
docker compose run --rm --no-deps -T --entrypoint /srv/webvirtcloud/venv/bin/python3 webvirtcloud \
  -c "import os,sqlite3,sys,tempfile; t=tempfile.mktemp(); open(t,'wb').write(sys.stdin.buffer.read()); [os.remove(p) for p in ('data/db.sqlite3-journal','data/db.sqlite3-wal','data/db.sqlite3-shm') if os.path.exists(p)]; sqlite3.connect(t).backup(sqlite3.connect('data/db.sqlite3'))" < "$b/db.sqlite3" &&
{ [ ! -f "$b/secret_key" ] || docker compose cp "$b/secret_key" webvirtcloud:/srv/webvirtcloud/data/; } &&
{ [ ! -f "$b/local_settings.py" ] || docker compose cp "$b/local_settings.py" webvirtcloud:/srv/webvirtcloud/data/; } &&
docker compose cp "$b/node_id" webvirtcloud:/srv/webvirtcloud/data/ &&
{ [ ! -d "$b/ssh" ] || docker compose cp "$b/ssh/." webvirtcloud:/var/www/.ssh/; } &&
{ [ ! -d "$b/pki" ] || docker compose cp "$b/pki/." webvirtcloud:/var/www/.pki/; } &&
docker compose up -d    # the container migrates and fixes ownership and modes at start
```

Installer and manual installation, from a root shell (`nginx` instead of `www-data` on RHEL / openSUSE / openEuler), with your `/etc/default/webvirtcloud` in place first. A backup of an older version has a `settings.py` instead of `local_settings.py`: carry your own values from it into [`data/local_settings.py`](configuration.md#local-settings).

```bash
b=/root/webvirtcloud-backup-YYYYMMDD-HHMMSS
systemctl stop webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
cd /srv/webvirtcloud &&
{ [ ! -f /etc/default/webvirtcloud ] || { set -a; . /etc/default/webvirtcloud; set +a; }; } &&
venv/bin/python3 -c "import os,sqlite3,sys; [os.remove(p) for p in ('db.sqlite3-journal','db.sqlite3-wal','db.sqlite3-shm') if os.path.exists(p)]; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect('db.sqlite3'))" "$b/db.sqlite3" &&
{ [ ! -f "$b/node_id" ] || cp "$b/node_id" data/; } && { [ ! -f "$b/secret_key" ] || cp "$b/secret_key" data/; } &&
{ [ ! -f "$b/local_settings.py" ] || cp "$b/local_settings.py" data/; } &&
mkdir -p ~www-data/.ssh && { [ ! -d "$b/ssh" ] || cp -r "$b"/ssh/. ~www-data/.ssh/; } &&
mkdir -p ~www-data/.pki && { [ ! -d "$b/pki" ] || cp -r "$b"/pki/. ~www-data/.pki/; } &&
venv/bin/python3 manage.py migrate &&
chown -R www-data:www-data data ~www-data/.ssh ~www-data/.pki &&
chmod 700 data ~www-data/.ssh ~www-data/.pki && chmod -R go-rwx data && { [ ! -f db.sqlite3 ] || chmod 600 db.sqlite3; } &&
systemctl start webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
```
