# Configuration

## Environment variables

| Variable | Effect |
| --- | --- |
| `ALLOWED_HOSTS` | extra host names/IPs the panel answers to (comma-separated, `*` for any; a network such as `192.0.2.0/24` is refused at start); other hosts get 400 |
| `CSRF_TRUSTED_ORIGINS` | extra trusted origins, e.g. `https://wvc.example.com` |
| `WEBVIRTCLOUD_HTTPS=1` | HTTPS profile, see [HTTPS and reverse proxy](#https-and-reverse-proxy) |
| `WEBVIRTCLOUD_SERIAL_CONSOLE=1` | serial console, see [Serial console](#serial-console) |
| `WEBVIRTCLOUD_DEBUG=1` | Django debug mode: error pages show the traceback and settings; for trying things out only, never on a panel others use |
| `WEBVIRTCLOUD_DB_HOST` | use PostgreSQL instead of sqlite (new installs); `WEBVIRTCLOUD_DB_PORT`/`_NAME`/`_USER`/`_PASSWORD` default to 5432/webvirtcloud/webvirtcloud/empty |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | SMTP for e-mail OTP; `EMAIL_USE_TLS` is 1 (STARTTLS, the default) or 0; the sender `DEFAULT_FROM_EMAIL` defaults to `EMAIL_HOST_USER` |
| `TZ` | time zone of the panel's dates and times and, in Docker, of the container (its daily backup), e.g. `Europe/Istanbul`; default UTC (the installer writes the server's zone into `data/local_settings.py`, which wins) |
| `WEBVIRTCLOUD_LOG_FILE` | log file (default `data/webvirtcloud.log`; a relative path is from the panel's directory; rotated at 10 MB × 5) |
| `SECRET_KEY` | Django secret key (default: the `data/secret_key` file) |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | the first superuser, read by the first `migrate` only, see [First login](install.md#first-login) |

The on/off variables take `1` or `0`; any other value, such as `true`, stops the panel at start with an error naming the variable.

### Where to set them

**Docker:** the `environment:` list of `docker-compose.override.yml`; every process in the container gets it. Then:

```bash
docker compose up -d
```

**Installer and manual installation:** `/etc/default/webvirtcloud` (root, mode 600), one `NAME='value'` per line (single quotes: systemd and the shell then read the same value). Then:

```bash
systemctl restart webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
```

### Workers

gunicorn runs at most 8 workers (fewer on hosts with under 4 CPUs), in Docker 4, of 4 threads each; each worker takes about 140 MB and sends at most 2 requests at a time to one compute. To change it, set `GUNICORN_CMD_ARGS=--workers N` in a drop-in of `webvirt-cloud` (`systemctl edit webvirt-cloud`: `[Service]` and `Environment="GUNICORN_CMD_ARGS=--workers N"`) or in `docker-compose.override.yml`.

## Local settings

Options that are not environment variables (LDAP, `OTP_ENABLED`, `LOGIN_TRUSTED_PROXIES` or any other setting of `webvirtcloud/settings.py`) go into `data/local_settings.py`. `settings.py` runs it after its own defaults, with their names at hand, so it sets or changes any of them (`ALLOWED_HOSTS += [...]`). Updates replace `settings.py` and leave this file alone. For example:

```python
TIME_ZONE = "Europe/Istanbul"
ALLOWED_HOSTS += ["wvc.example.com"]
OTP_ENABLED = True
```

- It uses the names of `settings.py`, not of the environment variables: a line `WEBVIRTCLOUD_HTTPS = 1` does nothing; `SERIAL_CONSOLE_ENABLED = True` sets what `WEBVIRTCLOUD_SERIAL_CONSOLE=1` sets.
- Its values win over the environment's.
- A value `settings.py` derives from another is not derived again: with `EMAIL_HOST_USER` set here, set `DEFAULT_FROM_EMAIL` here too. The log file is set only with `WEBVIRTCLOUD_LOG_FILE` in the environment.
- The installer writes the server's time zone, the noVNC port and its names and IPs into it.
- It may hold passwords (LDAP): keep it the panel user's with mode 600.

After a change, on an installer or manual installation:

```bash
systemctl restart webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
```

Docker keeps it in the `webvirtcloud-data` volume. Write it next to the compose file, then (the start makes it the panel user's):

```bash
docker compose cp local_settings.py webvirtcloud:/srv/webvirtcloud/data/
docker compose restart webvirtcloud
```

## Running manage.py

Installer and manual installation, from a root shell (`nginx` instead of `www-data` on RHEL / openSUSE):

```bash
cd /srv/webvirtcloud
[ ! -f /etc/default/webvirtcloud ] || { set -a; . /etc/default/webvirtcloud; set +a; }
runuser -u www-data -- venv/bin/python3 manage.py <command>
```

Docker, in the directory you installed from:

```bash
docker compose exec -u www-data webvirtcloud venv/bin/python3 manage.py <command>
```

## HTTPS and reverse proxy

For a panel served over HTTPS:

- set `WEBVIRTCLOUD_HTTPS=1`: session and CSRF cookies become HTTPS-only, HTTP is redirected to HTTPS (except `/datasource/`, which VMs fetch over HTTP), and HSTS is sent for one year;
- add the HTTPS origin to `CSRF_TRUSTED_ORIGINS`, e.g. `CSRF_TRUSTED_ORIGINS=https://wvc.example.com` and `WEBVIRTCLOUD_HTTPS=1` in `/etc/default/webvirtcloud`.

A proxy that ends TLS sends `X-Forwarded-Proto: https`.

Failed logins are counted per client address, so the panel must see the real one, over HTTP too:

- **Only the bundled nginx:** nothing more; it passes the client address in `X-Real-IP`.
- **A proxy in front of the bundled nginx:** set nginx's `set_real_ip_from` / `real_ip_header` for that proxy, or all clients share its address.
- **A proxy that replaces the bundled nginx:** it sets `X-Real-IP` itself. On another machine (gunicorn bound beyond 127.0.0.1), it must also be in `LOGIN_TRUSTED_PROXIES` in [`data/local_settings.py`](#local-settings).

## Cloud-init datasource

WebVirtCloud serves cloud-init metadata to guest instances: the hostname, and the SSH keys of the VM's users for the image's default user. The panel finds the VM by the reverse DNS name of the address the request comes from: its first label must be the name of exactly one VM, or no keys are sent. The host in the URL must be in `ALLOWED_HOSTS`:

```yaml
datasource:
  OpenStack:
    metadata_urls: [ "http://wvc.example.com/datasource" ]
```

Without the network: tick **Cloud-init seed** (Advanced) when creating a VM. The VM gets a CD-ROM with its hostname and your SSH keys (a NoCloud seed, `cidata-<uuid>.iso` in the disk's directory pool), which the image's cloud-init reads at first boot; it is deleted with the VM's disks.

### A template for the seed

Distribution cloud images (`GenericCloud`, `genericcloud`) come with cloud-init. A template installed from an ISO needs it once:

1. Start a VM on the template disk and install cloud-init in it: `dnf install -y cloud-init` or `apt install -y cloud-init`.
2. Remove what makes it this machine and shut it down:

   ```sh
   cloud-init clean --logs --seed
   truncate -s 0 /etc/machine-id
   poweroff
   ```

   Empty `/etc/machine-id`, do not delete it: without the file a Debian 12 clone gets no DHCP address (`cloud-init clean --machine-id` deletes it there).
3. Turn on **Settings > Options > Use as a template**, so the VM is not started again.

Create VMs with **Clone from template**, this VM's disk as **Template volume** and **Cloud-init seed** ticked. At first boot a VM takes its name as hostname and gets new SSH host keys and a new machine-id; your keys go to the image's default user (`default_user` in `/etc/cloud/cloud.cfg`, for example `almalinux` or `debian`), and `cloud-init status` says `done`. The seed sets no password and no static address: the network comes up with DHCP. A copy made on the VM's **Clone** tab gets no seed.

## Two-factor login (OTP)

Set `OTP_ENABLED = True` in [`data/local_settings.py`](#local-settings) to ask for a one-time code at login. It is per user: a user without a confirmed device signs in with the password alone.

The QR code is mailed as a link to a page that shows it, good for one hour: the mail does not hold the code's secret. Email OTP QR code on a user's page (Users) sends it; Lost OTP? on the login page sends it to an enrolled user who gives their address.

## Alerts

On the Settings page (Alerts), **Alert e-mail addresses** get a mail, through the server's SMTP settings (`EMAIL_HOST` and the others, as for OTP), and **Alert webhook** a JSON POST (`subject`, `text`, `time`; Slack and Mattermost take it) when a backup job fails, a scheduled backup is not taken (not for a host in maintenance), the daily target check finds backups missing, a verification finds a backup damaged, a job ends uncertain, or a fault stops or pauses a VM (a disk error, a crash, a kernel panic: the reasons the VM page shows; once a fault, read every minute from each host, so told within two minutes). The job worker sends them within a minute and tries a failed channel again for ten minutes.

## Health check

`/healthz`, without a login, answers 200 while the database answers and the job worker runs, 503 otherwise: point a monitor at it. The Docker image's health check reads it too.

## Serial console

A VM without graphics (no `<graphics>` device, a `<console type='pty'>`) opens a serial console (xterm.js) instead of VNC. It is off by default. To turn it on, set `WEBVIRTCLOUD_SERIAL_CONSOLE=1` (Docker: in `docker-compose.override.yml`, then `docker compose up -d`) or `SERIAL_CONSOLE_ENABLED = True` in [`data/local_settings.py`](#local-settings) and `systemctl restart webvirt-cloud webvirt-socketiod`.

- The VM page's Settings → Console switches a shut-off VM between VNC and serial (Console type). A new VNC console takes the form's other fields; on a TCP or TLS compute it needs Listen on: All interfaces (SSH and socket computes reach a localhost console).
- The guest must use its serial port: a login prompt needs `systemctl enable --now serial-getty@ttyS0`, boot messages need the kernel parameter `console=ttyS0,115200`. The console shows only what the guest writes after it opens; press Enter for a new prompt.
- socketiod listens on 127.0.0.1:6081; the page reaches it through nginx's `/socket.io/` location on the panel's own address.
- It accepts the console page's signed token, which expires after 120 s, only from a session of the user it was given to, as noVNC does. An open console checks its user's access about every 10 s and closes once it is lost.
- One console per VM, at most 20 at a time; a second one is refused with the reason, except a superuser's, which takes the console over.
- novncd and socketiod log to the journal (`journalctl -u webvirt-novncd -u webvirt-socketiod`) or, in Docker, to `docker logs`: a console that was refused or could not connect says why there.
