# Updating

Every update starts with a backup in its own directory (mode 700, named by date) that holds the database, the commit it was taken from, for Docker the TLS client certificates and, for installer and manual installations, `data/local_settings.py` (and a `settings.py` of an older version), the nginx config, `/etc/default/webvirtcloud` if there is one and migrations an old installer generated (`local-migrations.tar`). The database is copied with SQLite's backup API, which also finishes a write interrupted by a crash. This covers sqlite only; with PostgreSQL (`WEBVIRTCLOUD_DB_HOST`), back up that database yourself before updating.

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

On each compute that ran gstfsd under supervisor, remove its program (`/etc/supervisor/conf.d/gstfsd.conf` on Debian / Ubuntu, `/etc/supervisord.d/gstfsd.ini` on RHEL / openSUSE), run `sudo supervisorctl update`, install gstfsd as in [Adding a Compute Node](compute-nodes.md), step 3, and remove supervisor once nothing else uses it.

## Installer and manual installation

From a root shell:

```bash
(set -o pipefail &&
 git -C /srv/webvirtcloud -c safe.directory=/srv/webvirtcloud fetch -q origin &&
 git -C /srv/webvirtcloud -c safe.directory=/srv/webvirtcloud show origin/master:update.sh | bash)
```

- It runs the newest `update.sh` of the repository, also on an installation that has none yet. Another directory than `/srv/webvirtcloud`: set it in the command and `APP_PATH` for `bash`; the units get it.
- Nothing in the installation changes until its checks pass; files of the repository changed by hand stop it, listed. With PostgreSQL (the database Django is set up with), back that database up first and run it with `... | bash -s -- --database-backed-up`.
- An installation of an older version has its own `webvirtcloud/settings.py`: it stops and lists the lines that differ from that version's template: your own. Put your own values into [`data/local_settings.py`](configuration.md#local-settings) and run it again. Typical ones are `TIME_ZONE`, `WS_PORT`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, LDAP and, with PostgreSQL, your `DATABASES`: the default is sqlite, so without it `migrate` would make a new, empty sqlite database and the panel would start on that. A literal `SECRET_KEY = "..."` (older installers wrote it there) goes into `data/secret_key` instead (with no key every page fails, with another every user is signed out); keep `SHOW_PROFILE_EDIT_PASSWORD` for this one update if you have it (migration `accounts.0008` reads it), then delete it.
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

## Behavior changes

What an update from an older version changes for operators and users. `manage.py` below is, from a root shell in `/srv/webvirtcloud` with `/etc/default/webvirtcloud` loaded if you use it, `runuser -u www-data -- venv/bin/python3 manage.py` (`nginx` on RHEL / openSUSE), in Docker `docker compose exec -u www-data webvirtcloud venv/bin/python3 manage.py`:

- Requests for a host not in `ALLOWED_HOSTS` get 400. The installer writes the server's names and IPs; add more with the `ALLOWED_HOSTS` env var. The cloud-init datasource host must be allowed too.
- Logging out needs a POST; a GET to `/accounts/logout/` gets 405.
- The API accepts only a session from the login form or an API token (no HTTP Basic), and the API docs need a login. Sessions opened through the old password-only doors skip OTP; end them once after the update (everyone signs in again): `manage.py shell -c "from django.contrib.sessions.models import Session; Session.objects.all().delete()"`.
- Failed logins lock a user (django-axes): the sign-in page then says how long. The limit and lock time are on the Settings page; a locked user is marked on the Users page, and a superuser ends the lock with Unlock sign-in on the user's page. A sign-in lasts the session length set on the Settings page (24 hours by default). A sign-in notice set there (e.g. planned maintenance) is shown above the sign-in form.
- Changing one's own password is the "Can change password" permission (per user or group; new users have it); `SHOW_PROFILE_EDIT_PASSWORD` is gone.
- The admin's first-login password change survives losing `data/admin_password` (migration `accounts.0007`); run `migrate` as a user who can read that file.
- A new VM and each clone get a random VNC password of their own (clones no longer share their source's). The console page sends it for a user with **Open a console without the VM's console password**, which a new user has unless unticked; others are asked for it. Existing VMs keep theirs.
- An `admin` account that still has the password `admin` (the first user of versions up to v2.0.0) must change it at its next login, and its API tokens are refused until then (migration `accounts.0013`).
- `webvirtcloud/settings.py` is part of the code, and every update replaces it; an installation's own settings are in [`data/local_settings.py`](configuration.md#local-settings). `update.sh` has them moved there once from an older version's own `settings.py`; in Docker, remove a mounted `settings.py` from `docker-compose.override.yml`.
- The VNC console connects to `/novncd/` on the panel's own address through nginx, and the serial console to `/socket.io/`: they work on HTTPS and behind another proxy without settings. `WS_PUBLIC_PORT`, `WS_PUBLIC_HOST`, `WS_PUBLIC_PATH`, `WS_CERT` and `SOCKETIO_PUBLIC_HOST`/`_PORT`/`_PATH` are gone; remove them from `docker-compose.override.yml`, `/etc/default/webvirtcloud` or `data/local_settings.py`, and close port 6080 in the firewall.
- Installer and manual installations run the panel as systemd units (`webvirt-cloud`, `webvirt-novncd`, `webvirt-socketiod`, `webvirt-worker`, `webvirt-backup.timer`) and computes run `webvirt-gstfsd`, instead of supervisor; see [Moving from supervisor to systemd](#moving-from-supervisor-to-systemd). Service settings go into `/etc/default/webvirtcloud`, service output into the journal (`journalctl -u webvirt-cloud`); the app log stays in `data/`. novncd and socketiod run sandboxed (read-only system directories, no `/home`).
- gstfsd does only what the panel signs with the host's key: it does not start without `GSTFSD_KEY` in `/etc/default/webvirt-gstfsd`. On every compute, update gstfsd and its unit and make the key as in [Adding a Compute Node](compute-nodes.md), step 3 (a remote panel's `GSTFSD_BIND_HOST` and `GSTFSD_ALLOW_REMOTE` move into that file from `systemctl edit webvirt-gstfsd`), then enter the key on each compute's edit page.
- LDAP login's packages are in `conf/requirements-ldap.txt` and no longer installed by default, nor their build headers by the installer; the Docker image keeps them. An existing virtualenv keeps them, but only installing that file updates them (see [LDAP](ldap.md)).
- The themes ship compiled; picking one on the Settings page only saves its name, and the "Theme SASS Path" setting is gone. Browsers revalidate static files on each load: files cached before the update can stay until a hard reload (Ctrl+F5) of each page; an external caching proxy may need a purge.
- The panel backs itself up every day ([Backups](backups.md)); in Docker into a new volume, `webvirtcloud-backups`.
- The Docker image is built on Ubuntu 26.04 LTS (Python 3.14, libvirt 12) instead of 24.04; `docker compose up -d --build` rebuilds it.
- New passwords must pass Django's password validators: at least 8 characters, not a common password, not only digits, not like the user's name or e-mail. Existing passwords keep working.
- In Docker, the TLS client certificates of TLS computes are kept in a new volume, `webvirtcloud-pki` (`/var/www/.pki`), and backed up; put them there once ([Adding a Compute Node](compute-nodes.md), step 2).
- The SQLite database must be on a local file system (WAL). Outside compose, stop the Docker container with `docker stop -t 95 webvirtcloud` so the worker can finish running jobs.
- Long operations run as jobs in a worker process (`manage.py run_worker`): creating, cloning, migrating and deleting VMs, bulk power actions, moving disks, cloning and downloading volumes, taking and reverting snapshots, deleting external snapshots and VM backups. The page returns at once and the job panel and the Jobs page follow them. The API's VM create, migrate and delete answer 202 with the job and need a `submission_key`: a new one for each operation, the same one to retry it (a delete retried after its VM is gone gets 404). The create form no longer takes a console password; set it on the VM page.
- An API error other than a field the request got wrong (which answers with the fields) is `{"detail": ...}` with a status that says what it is: 404 for a VM, pool or volume read or deleted that the host does not have, 409 for a volume in use, a template started or a stopped pool, 503 for a host that cannot be reached (all were 400 or 200 before); an unknown API URL answers JSON.
- An ISO upload is tracked as a job that can be cancelled. The browser sends the file, so stay on the page until it ends; an upload left idle for an hour is ended and its partial file deleted.
- A clone of a running VM (libvirt 11.10 or later, local file disks, no TPM) locks the VM until the copy ends and can be cancelled; cancelling a clone of a shut-off VM has no effect. A job that ends uncertain keeps its VM locked until a superuser resolves it on its job page.
- The job worker runs at most half of its concurrency (Settings, at least one) of one host's jobs at a time, so a host that does not answer cannot take every slot.
- A new VM is made in three steps (host, machine, details); flavors are presets that fill vCPU, memory and disk size. "VM Clone Auto Migrate" is removed; a clone stays on its source host.
- A user's quota counts, for each VM, the larger of its running and its next-start vCPUs, memory and disks, and a queued clone as one VM. A user can be over the quota after the update; nothing is stopped, but new VMs, clones and raises are refused until it fits.
- A user who is not a superuser names a clone with one of the free names the clone form offers; other names are refused.
- A template VM is changed or deleted only by superusers and staff owners with the matching permission; other owners can still view, open the console and clone it.
- On a running VM the edit forms show the settings as they will be at the next start, so saving an edit no longer reverts another pending change.
- External snapshots need libvirt 9.9 or newer on the computes. libvirt 9.10 (openEuler 24.03 LTS) refuses to revert a snapshot taken without memory of a running or paused VM ("Invalid target domain state 'disk-snapshot'"); 11.10 reverts it. A VM's snapshots form one chain: after a revert, delete the newer snapshots before taking another. An internal snapshot is reverted only on a shut-off VM. Snapshot names no longer get an `s1.` prefix. A snapshot an older version took of a UEFI VM can only be deleted, not reverted. On NFS, the qemu user needs write access to the image directory to remove merged snapshot files.
- A superuser limits a disk's I/O (IOPS and MiB/s, reads and writes together) under its Device details on the Disks tab; a running VM gets the limit at once.
- A storage volume a VM still needs (a disk, a backing file or a snapshot's file) is not deleted; deleting a VM with its files keeps a file another compute's VM or volume uses at the same path, and is refused before the VM is stopped when one of the other computes cannot be reached. A pool's page names the VMs of its host that use each volume and lists those the host does not use.
- A VM that vanishes from its compute, or whose compute is deleted, keeps its owners, tags, protection and schedules for `INSTANCE_OWNERSHIP_RETENTION_DAYS` (30) in case the same UUID comes back, and its backups are linked to it again; superusers manage these records on the "Removed VMs" page.
- The Logs page records who changed what (computes, users, groups, VM owners, settings, SSH keys, host networks, pools, volumes, interfaces, secrets and network filters), every login, failed login and lockout, and every page or API call answered 401 or 403 to a signed-in user or a request with credentials, with the address and the result (a VM hidden with 404 is not logged).
- On a host whose libvirt cannot change network interfaces (the udev backend: RHEL 9 and later, Debian 12), the interface pages offer no create, start, stop or delete.
- With SELinux (RHEL family, openEuler), systemd could not run the virtualenv's programs and the panel did not start. The installer now writes file context rules (`httpd_sys_content_t` for the panel, `bin_t` for `venv/bin`) instead of `chcon`, so a relabel keeps them. A manual installation runs `semanage fcontext -a -t bin_t "/srv/webvirtcloud/venv/bin(/.*)?"` and `restorecon -R /srv/webvirtcloud` once; an installer one runs the installer again.
