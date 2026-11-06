# WebVirtCloud
###### Python >=3.10 & Django 5.2 LTS (tested on Python 3.10 – 3.13)

WebVirtCloud is a **web visualization and management layer** for **libvirt**-based virtualization infrastructure.

> **libvirt is the single source of truth.** WebVirtCloud reads, displays and triggers actions on libvirt state, but it is never the primary orchestrator.

- An administrator can connect to libvirt directly with **`virt-manager`** or **`virsh`** and create, delete, rename or reconfigure virtual machines. WebVirtCloud detects these changes and updates its database accordingly.
- Virtual machines keep running **even when WebVirtCloud is stopped**; the application only reflects the current state of libvirt.
- WebVirtCloud is not a full automation platform like Proxmox. Its goal is to expose libvirt's functionality through the browser in an accessible, role-based and secure way.

```
┌─────────────────────────────────────────────────────┐
│               Administrator / User                  │
└────────────┬───────────────────┬────────────────────┘
             │ Web browser        │ virt-manager / virsh
             ▼                   ▼
┌────────────────────┐  ┌─────────────────────────────┐
│   WebVirtCloud     │  │   libvirt API (direct)      │
│   (web UI layer)   │◄─┤   — separate, independent   │
└────────┬───────────┘  └──────────────┬──────────────┘
         │ libvirt API                  │
         ▼                             ▼
┌──────────────────────────────────────────────────────┐
│               libvirtd (hypervisor daemon)           │
│                    QEMU / KVM                        │
└──────────────────────────────────────────────────────┘
```

WebVirtCloud and `virt-manager`/`virsh` can manage the same libvirt host **concurrently and independently**. WebVirtCloud picks up external changes the next time the instance list page is loaded.

## Features

* QEMU/KVM hypervisor management (multiple compute nodes), with each host's capacity and what its VMs were given
* Virtual machine lifecycle: create, delete, power management, clone (also of a running VM, with libvirt 11.10 or later), migrate (with or without shared storage), disk moves between pools
* Long operations (create, clone, delete, snapshots, migration, disk moves, ISO upload) run as jobs that the page follows and can cancel
* External snapshots (memory optional, guest file systems frozen through the agent)
* **External change detection:** VMs created, deleted or renamed via `virt-manager` or `virsh` are reconciled into the database automatically
* Real-time hypervisor and VM statistics (CPU, RAM, disk, network)
* Storage pool and volume management
* Network (with DHCP leases), interface, network filter and secret management
* PCI and USB devices of the host given to VMs
* UEFI Secure Boot and TPM 2.0 for new VMs, as Windows 11 needs
* Browser-based VNC console (noVNC) and serial console
* Role-based access control: users only see the VMs assigned to them, within their quota
* 2FA (OTP / TOTP) and failed-login lockout
* SSH public key and root password management (guest agent for a running VM, gstfsd for a shut-off one)
* Finding VMs by IP or MAC address, and a VM report as an Excel file
* An audit log of who changed what, with its result
* Cloud-init datasource interface (OpenStack metadata compatible) and NoCloud seed media
* REST API — OpenAPI 3.0 (Swagger & ReDoc), with API tokens
* LDAP / Active Directory integration (optional)
* Daily backups of the panel, with an optional off-site copy (restic over SFTP)
* English, Turkish and Simplified Chinese

## Contents

1. [Installation](#installation): [installer](#installer), [Docker](#docker), [manual](#manual-installation), [first login](#first-login)
2. [Adding a Compute Node](#adding-a-compute-node)
3. [Configuration](#configuration): [environment variables](#environment-variables), [HTTPS and reverse proxy](#https-and-reverse-proxy), [cloud-init datasource](#cloud-init-datasource), [LDAP](#ldap), [OTP](#two-factor-login-otp), [serial console](#serial-console)
4. [Backups](#backups): [off-site copy](#off-site-copy)
5. [Updating](#updating): [Docker](#docker-1), [installer and manual](#installer-and-manual-installation), [restore and rollback](#restore-and-rollback), [moving to a new machine](#moving-to-a-new-machine), [behavior changes](#behavior-changes)
6. [Usage](#usage): [users and permissions](#users-roles-and-permissions), [REST API](#rest-api), [screenshots](#screenshots)
7. [Development](#development)

## Installation

The installer supports Ubuntu 22.04 / 24.04 / 26.04, Debian 12 / 13, RHEL / Rocky Linux / AlmaLinux / Oracle Linux 10, openEuler 24.03 LTS, openSUSE Leap 15.x / Tumbleweed and SLES 15; the panel runs on a virtual machine, a physical host or a KVM host itself and needs Python 3.10 or newer. CI tests Python 3.10–3.13 on Ubuntu (sqlite, and PostgreSQL on 3.12) and the Docker image; the distro installs are not tested in CI. Pick one of the three ways below, then do the [first login](#first-login).

### Installer

```bash
curl -fsSL -O https://raw.githubusercontent.com/retspen/webvirtcloud/master/install.sh
chmod 744 install.sh
sudo ./install.sh
```

The installer writes the server's names and IPs to `ALLOWED_HOSTS`. Running it again keeps `settings.py`, the database, the secret key and the main nginx config, but replaces `/etc/nginx/conf.d/webvirtcloud.conf` and the systemd units; back up your own lines in the nginx config (TLS) first. Put your own service settings in `/etc/default/webvirtcloud` or in drop-ins (`systemctl edit webvirt-cloud`), which a re-run keeps.

### Docker

```bash
# 1. Clone repository:
git clone https://github.com/retspen/webvirtcloud
cd webvirtcloud

# 2. Set the names/IPs the panel is reached by (git pull never touches this file):
cat > docker-compose.override.yml <<'EOF'
services:
  webvirtcloud:
    environment:
      - ALLOWED_HOSTS=wvc.example.com,192.0.2.10
EOF

# 3. Start services:
docker compose up -d
```

The panel and its console are at `http://<server-ip>`. The database and secret key live in the `webvirtcloud-data` volume, the SSH keys in `webvirtcloud-ssh`, the TLS client certificates in `webvirtcloud-pki`, the [backups](#backups) in `webvirtcloud-backups`. Other settings go in the same `environment:` list, see [Environment variables](#environment-variables).

### Manual installation

Run the steps from a root shell (`sudo -i`). In step 3, replace the example `ALLOWED_HOSTS` with the names/IPs the panel (and the cloud-init datasource) is reached by.

The virtualenv is created with `--system-site-packages`: `libvirt-python` comes from the distro packages when its version satisfies `conf/requirements.txt`; otherwise pip builds it, which needs the `-dev`/`-devel` packages listed below. `lxml` is reused the same way; everything else comes from pip.

#### Ubuntu 22.04 / 24.04 / 26.04, Debian 12 / 13

```bash
# 1. System packages
apt-get update && apt-get -y install git python3-venv python3-dev python3-lxml python3-libvirt libvirt-dev zlib1g-dev libxslt1-dev nginx libsasl2-modules gcc pkg-config python3-guestfs libssl-dev

# 2. Code
git clone https://github.com/retspen/webvirtcloud /srv/webvirtcloud
cd /srv/webvirtcloud

# 3. Settings, allowed hosts and secret key
cp webvirtcloud/settings.py.template webvirtcloud/settings.py
sed -i 's|^ALLOWED_HOSTS = .*|ALLOWED_HOSTS = ["wvc.example.com", "192.0.2.10", "localhost", "127.0.0.1", "[::1]"]|' webvirtcloud/settings.py
mkdir -p data && python3 conf/runit/secret_generator.py > data/secret_key && chmod 600 data/secret_key

# 4. Virtualenv and dependencies
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r conf/requirements.txt

# 5. Database and static files (the first migrate creates the "admin" user)
python3 manage.py migrate
python3 manage.py collectstatic --noinput

# 6. systemd units (gunicorn, novncd, socketiod, the job worker and the daily backup) and nginx
cp conf/systemd/webvirt-{cloud,novncd,socketiod,worker,backup}.service conf/systemd/webvirt-backup.timer /etc/systemd/system/
cp conf/nginx/webvirtcloud.conf /etc/nginx/conf.d/
rm -f /etc/nginx/sites-enabled/default

# 7. Ownership, private files, start (the groups let the services reach a local libvirt and KVM)
chown -R www-data:www-data /srv/webvirtcloud
usermod -a -G libvirt,kvm www-data 2>/dev/null || true   # on a KVM host
chmod 700 data && chmod 600 webvirtcloud/settings.py db.sqlite3
systemctl daemon-reload && systemctl enable --now webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker webvirt-backup.timer
nginx -t && systemctl restart nginx
```

#### RHEL / Rocky Linux / AlmaLinux / Oracle Linux 10

```bash
# 1. System packages (libvirt-devel is in the CRB repository)
dnf -y install epel-release && crb enable
dnf -y install git python3-devel libvirt-devel python3-libvirt python3-lxml cyrus-sasl-md5 openssl-devel glibc gcc nginx python3-libguestfs iproute-tc policycoreutils-python-utils

# 2. Code
git clone https://github.com/retspen/webvirtcloud /srv/webvirtcloud
cd /srv/webvirtcloud

# 3. Settings, allowed hosts and secret key
cp webvirtcloud/settings.py.template webvirtcloud/settings.py
sed -i 's|^ALLOWED_HOSTS = .*|ALLOWED_HOSTS = ["wvc.example.com", "192.0.2.10", "localhost", "127.0.0.1", "[::1]"]|' webvirtcloud/settings.py
mkdir -p data && python3 conf/runit/secret_generator.py > data/secret_key && chmod 600 data/secret_key

# 4. Virtualenv and dependencies
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r conf/requirements.txt

# 5. Database and static files (the first migrate creates the "admin" user)
python3 manage.py migrate
python3 manage.py collectstatic --noinput

# 6. systemd units (gunicorn, novncd, socketiod, the job worker and the daily backup, as nginx) and nginx
for u in cloud novncd socketiod worker backup; do sed 's/^\(User\|Group\)=.*/\1=nginx/' conf/systemd/webvirt-$u.service > /etc/systemd/system/webvirt-$u.service; done
cp conf/systemd/webvirt-backup.timer /etc/systemd/system/
cp conf/nginx/webvirtcloud.conf /etc/nginx/conf.d/
# make sure the default server block in /etc/nginx/nginx.conf does not also listen on port 80

# 7. Ownership, private files, SELinux, firewall, start (the groups let the services reach a local libvirt and KVM)
chown -R nginx:nginx /srv/webvirtcloud
usermod -a -G libvirt,kvm nginx 2>/dev/null || true   # on a KVM host
chmod 700 data && chmod 600 webvirtcloud/settings.py db.sqlite3
# nginx reads the static files, systemd runs the virtualenv's programs
semanage fcontext -a -t httpd_sys_content_t "/srv/webvirtcloud(/.*)?" 2>/dev/null || true
semanage fcontext -a -t bin_t "/srv/webvirtcloud/venv/bin(/.*)?" 2>/dev/null || true
restorecon -R /srv/webvirtcloud 2>/dev/null || true
setsebool -P httpd_can_network_connect on 2>/dev/null || true
firewall-cmd --add-service=http --permanent 2>/dev/null || true
firewall-cmd --reload 2>/dev/null || true
systemctl daemon-reload && systemctl enable --now webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker webvirt-backup.timer
systemctl enable nginx && nginx -t && systemctl restart nginx
```

#### openSUSE Leap 15.x / Tumbleweed, SLES 15

```bash
# 1. System packages (Python 3.11 stack)
zypper --non-interactive install -y git hostname python311 python311-base python311-devel python311-pip python311-libvirt-python python311-lxml libvirt-devel libopenssl-devel gcc pkg-config nginx

# 2. Code
git clone https://github.com/retspen/webvirtcloud /srv/webvirtcloud
cd /srv/webvirtcloud

# 3. Settings, allowed hosts and secret key
cp webvirtcloud/settings.py.template webvirtcloud/settings.py
sed -i 's|^ALLOWED_HOSTS = .*|ALLOWED_HOSTS = ["wvc.example.com", "192.0.2.10", "localhost", "127.0.0.1", "[::1]"]|' webvirtcloud/settings.py
mkdir -p data && python3.11 conf/runit/secret_generator.py > data/secret_key && chmod 600 data/secret_key

# 4. Virtualenv and dependencies
python3.11 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r conf/requirements.txt

# 5. Database and static files (the first migrate creates the "admin" user)
python3 manage.py migrate
python3 manage.py collectstatic --noinput

# 6. systemd units (gunicorn, novncd, socketiod, the job worker and the daily backup, as nginx) and nginx
for u in cloud novncd socketiod worker backup; do sed 's/^\(User\|Group\)=.*/\1=nginx/' conf/systemd/webvirt-$u.service > /etc/systemd/system/webvirt-$u.service; done
cp conf/systemd/webvirt-backup.timer /etc/systemd/system/
cp conf/nginx/webvirtcloud.conf /etc/nginx/conf.d/
# make sure the default server block in /etc/nginx/nginx.conf does not also listen on port 80

# 7. Ownership, private files, start (the groups let the services reach a local libvirt and KVM)
chown -R nginx:nginx /srv/webvirtcloud
usermod -a -G libvirt,kvm nginx 2>/dev/null || true   # on a KVM host
chmod 700 data && chmod 600 webvirtcloud/settings.py db.sqlite3
systemctl daemon-reload && systemctl enable --now webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker webvirt-backup.timer
systemctl enable nginx && nginx -t && systemctl restart nginx
```

### First login

The first `migrate` creates a superuser named `admin` with a random password, written to `data/admin_password` (mode 0600):

```bash
sudo cat /srv/webvirtcloud/data/admin_password            # installer or manual installation
docker compose exec webvirtcloud cat data/admin_password   # Docker
```

Sign in at `http://<server-ip>`; you must set a new password at the first login, and the file is then deleted. To choose the name or password yourself, set `ADMIN_USERNAME` and/or `ADMIN_PASSWORD` in the environment before that first `migrate`; a password you set is not written to the file and need not be changed. A lost password is reset with `python3 manage.py changepassword admin` (Docker: `docker compose exec webvirtcloud /sbin/setuser www-data venv/bin/python3 manage.py changepassword admin`).

## Adding a Compute Node

A compute node is a KVM host the panel manages over libvirt.

1. Install KVM and libvirt. The bootstrap script handles Ubuntu, Debian, CentOS, Fedora, Rocky Linux and AlmaLinux 10, openEuler 24.03 LTS, openSUSE and SLES. On RHEL, which needs EPEL from its release RPM, install the `qemu-kvm` and `libvirt` packages yourself and enable `virtqemud.socket` (plus `virtproxyd-tcp.socket` for TCP):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/retspen/webvirtcloud/master/dev/libvirt-bootstrap.sh | sudo sh
   # or, from a cloned repository: sudo sh ./dev/libvirt-bootstrap.sh
   ```

   The new VM form offers UEFI, UEFI Secure Boot (with Microsoft's keys, for Windows 11) and a TPM 2.0 only when the host's libvirt finds the UEFI firmware and swtpm: install `ovmf swtpm-tools` (Debian / Ubuntu) or `edk2-ovmf swtpm swtpm-tools` (RHEL family, openEuler) if they are missing.

2. For SSH connections, give the user the panel runs as an SSH key and copy it to the compute node. **Use only the block for your installation type:** a key set up with the host commands is not seen by the panel in Docker. `ssh-copy-id` asks for the compute node's root password once. `accept-new` accepts a new host's key on first connect and refuses a changed one.

   **Installer or manual installation**, on the panel host:

   ```bash
   U=www-data   # the web service user: www-data on Debian/Ubuntu, nginx on RHEL/openSUSE
   H=$(getent passwd $U | cut -d: -f6)
   sudo install -d -m 700 -o $U -g $U $H/.ssh
   sudo -u $U ssh-keygen -t ed25519 -N "" -f $H/.ssh/id_ed25519
   printf 'Host *\n  StrictHostKeyChecking accept-new\n' | sudo -u $U tee $H/.ssh/config > /dev/null
   sudo chmod 600 $H/.ssh/config
   sudo -u $U ssh-copy-id root@<compute-node-ip>
   sudo -u $U ssh root@<compute-node-ip> true   # no password or prompt: ready
   ```

   **Docker**, on the Docker host from the directory with `docker-compose.yml`; the commands run inside the container (always as `www-data`: the keys are kept in the `webvirtcloud-ssh` volume, and a key made as root is not used by the panel):

   ```bash
   docker compose exec -u www-data webvirtcloud ssh-keygen -t ed25519 -N "" -f /var/www/.ssh/id_ed25519
   docker compose exec -u www-data webvirtcloud sh -c 'printf "Host *\n  StrictHostKeyChecking accept-new\n" > ~/.ssh/config && chmod 600 ~/.ssh/config'
   docker compose exec -u www-data webvirtcloud ssh-copy-id root@<compute-node-ip>
   docker compose exec -u www-data webvirtcloud ssh root@<compute-node-ip> true   # no password or prompt: ready
   ```

   For TLS connections, put the CA certificate and the panel's client certificate and key in the panel user's `~/.pki/libvirt/` as `cacert.pem`, `clientcert.pem` and `clientkey.pem`, readable only by that user: `$H/.pki/libvirt/` with the installer; in Docker `/var/www/.pki/libvirt/` (the `webvirtcloud-pki` volume), owned by `www-data`.

3. Install or update the `gstfsd` daemon on the compute node (the bootstrap script does this too). It sets the root password and SSH key of a shut-off VM:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/retspen/webvirtcloud/master/conf/daemon/gstfsd | sudo tee /usr/local/bin/gstfsd > /dev/null
   sudo chmod +x /usr/local/bin/gstfsd
   curl -fsSL https://raw.githubusercontent.com/retspen/webvirtcloud/master/conf/systemd/webvirt-gstfsd.service | sudo tee /etc/systemd/system/webvirt-gstfsd.service > /dev/null
   # its key, once: keep the file when you update gstfsd
   [ -s /etc/default/webvirt-gstfsd ] || sudo sh -c 'umask 077 && echo "GSTFSD_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")" > /etc/default/webvirt-gstfsd'
   sudo chown root:root /etc/default/webvirt-gstfsd && sudo chmod 600 /etc/default/webvirt-gstfsd
   sudo systemctl daemon-reload && sudo systemctl enable webvirt-gstfsd && sudo systemctl restart webvirt-gstfsd
   sudo cat /etc/default/webvirt-gstfsd   # the key for step 4
   ```

   gstfsd does only what the panel signs with this key. It listens on 127.0.0.1:16510 only, which serves a panel on the compute itself that adds it as `localhost` or `127.0.0.1`. A panel on another machine or in a container (the Docker setup, also on the compute) reaches it at the compute's address; let it in:

   ```bash
   sudo sed -i '/^GSTFSD_BIND_HOST=/d; /^GSTFSD_ALLOW_REMOTE=/d' /etc/default/webvirt-gstfsd
   printf 'GSTFSD_BIND_HOST=0.0.0.0\nGSTFSD_ALLOW_REMOTE=1\n' | sudo tee -a /etc/default/webvirt-gstfsd > /dev/null
   sudo systemctl restart webvirt-gstfsd
   ```

   Its traffic is not encrypted, and a password hash crosses it: allow TCP 16510 only from the panel's IP, on a network you trust.

   A running VM gets them through its QEMU guest agent instead, without gstfsd. On RHEL-family guests, SELinux lets the agent add SSH keys only after `sudo setsebool -P virt_qemu_ga_manage_ssh on` inside the guest.

   A compute that ran gstfsd under supervisor: remove its program first (`/etc/supervisor/conf.d/gstfsd.conf` on Debian / Ubuntu, `/etc/supervisord.d/gstfsd.ini` on RHEL / openSUSE), run `sudo supervisorctl update`, and remove supervisor once nothing else uses it.

4. Add the compute on the panel's Computes page, with the `GSTFSD_KEY` value from step 3 as its gstfsd key.

Firewall: the compute's VNC ports (`5900`–`65535`) must accept connections **only** from the panel's IP, never from public networks.

### Migration

- **Shared storage:** define it as a storage pool on every host. A VM migrates when its disk, backing and ISO files and block devices are volumes of the destination's pools.
- **Address:** a migrating VM goes to the destination's address on the Computes page; for a dedicated migration network, set the compute's **Migration address** on its edit page.
- **Without shared storage:** after choosing the destination, the **Disks** list shows each disk and the destination pools that can take a copy (directory, filesystem and NFS pools; a pool with a file of the same name refuses it); a disk on storage both hosts share can stay there. Plain raw or qcow2 disks without a backing file are copied, through the destination's migration port range (49152-49215 by default). **Delete the source files of copied disks** removes them after the migration, unless another VM or volume uses them.
- **Shut-off VMs:** a shut-off VM moves offline, with its NVRAM file (UEFI). When its disks are copied or it has a TPM, it is started paused for the migration instead (its CPUs never run) and shut off on the destination.

If libvirt warns `Host SMBIOS information is not available`, install `dmidecode` (`apt-get`, `dnf` or `zypper install -y dmidecode`) and restart `libvirtd`.

## Configuration

### Environment variables

| Variable | Effect |
| --- | --- |
| `ALLOWED_HOSTS` | extra host names/IPs the panel answers to (comma-separated, `*` for any); other hosts get 400 |
| `CSRF_TRUSTED_ORIGINS` | extra trusted origins, e.g. `https://wvc.example.com` |
| `WEBVIRTCLOUD_HTTPS=1` | HTTPS profile, see [HTTPS and reverse proxy](#https-and-reverse-proxy) |
| `WEBVIRTCLOUD_SERIAL_CONSOLE=1` | serial console, see [Serial console](#serial-console) |
| `WEBVIRTCLOUD_DB_HOST` | use PostgreSQL instead of sqlite (new installs); `WEBVIRTCLOUD_DB_PORT`/`_NAME`/`_USER`/`_PASSWORD` default to 5432/webvirtcloud/webvirtcloud/empty |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | SMTP for e-mail OTP |
| `WEBVIRTCLOUD_LOG_FILE` | log file (default `data/webvirtcloud.log`, rotated at 10 MB × 5) |
| `SECRET_KEY` | Django secret key (default: the `data/secret_key` file) |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | the first superuser, read by the first `migrate` only, see [First login](#first-login) |

Where to set them:

- **Docker:** the `environment:` list of `docker-compose.override.yml`; every process in the container gets it.
- **Installer and manual installation:** edit `webvirtcloud/settings.py`, or put them in `/etc/default/webvirtcloud` (root, mode 600), one `NAME='value'` per line (single quotes: systemd and the shell then read the same value); the panel's services read it. Then `systemctl restart webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker`, and load the file before running `manage.py`: `set -a; . /etc/default/webvirtcloud; set +a`.

Some options exist only in `settings.py` (LDAP, `OTP_ENABLED`, `LOGIN_TRUSTED_PROXIES`). Docker builds that file from the template in each new container; to keep such options there, mount your own copy and update it from the template after each update:

```bash
docker compose exec webvirtcloud cat webvirtcloud/settings.py > settings.py   # then edit it
```

add it to `docker-compose.override.yml` and run `docker compose up -d`:

```yaml
services:
  webvirtcloud:
    volumes:
      - ./settings.py:/srv/webvirtcloud/webvirtcloud/settings.py
```

The container makes the file the panel user's (uid 33) with mode 600; edit it as root.

gunicorn runs at most 8 workers (fewer on hosts with under 4 CPUs) of 4 threads each; to change it, set `GUNICORN_CMD_ARGS=--workers N` in a drop-in of `webvirt-cloud` (`systemctl edit webvirt-cloud`: `[Service]` and `Environment="GUNICORN_CMD_ARGS=--workers N"`) or in `docker-compose.override.yml`.

### HTTPS and reverse proxy

For a panel served over HTTPS:

- set `WEBVIRTCLOUD_HTTPS=1`: session and CSRF cookies become HTTPS-only, HTTP is redirected to HTTPS (except `/datasource/`, which VMs fetch over HTTP), and HSTS is sent for one year;
- add the HTTPS origin to `CSRF_TRUSTED_ORIGINS`, e.g. `CSRF_TRUSTED_ORIGINS=https://wvc.example.com` and `WEBVIRTCLOUD_HTTPS=1` in `/etc/default/webvirtcloud`.

TLS can end at the bundled nginx or at a proxy in front of it; such a proxy must send `X-Forwarded-Proto: https`. Failed logins are counted per client address, which the bundled nginx passes in `X-Real-IP`. A proxy that replaces the bundled nginx must set `X-Real-IP` itself; one on another machine (gunicorn bound beyond 127.0.0.1) must also be in `LOGIN_TRUSTED_PROXIES` in `settings.py`. With a proxy in front of the bundled nginx, configure nginx's `set_real_ip_from` / `real_ip_header` for that proxy, or all clients share its address.

Every page is sent with `X-Frame-Options: DENY` and `Content-Security-Policy: script-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`: the panel runs only scripts it serves itself, cannot be shown in a frame, and its forms post only to its own origin.

### Cloud-init datasource

WebVirtCloud serves cloud-init metadata to guest instances: the hostname, and the SSH keys of the VM's users for the image's default user. The host in the URL must be in `ALLOWED_HOSTS`:

```yaml
datasource:
  OpenStack:
    metadata_urls: [ "http://wvc.example.com/datasource" ]
```

Without the network: tick **Cloud-init seed** (Advanced) when creating a VM. The VM gets a CD-ROM with its hostname and your SSH keys (a NoCloud seed, `cidata-<uuid>.iso` in the disk's directory pool), which the image's cloud-init reads at first boot; it is deleted with the VM's disks.

### LDAP

The options below are set in `webvirtcloud/settings.py` (Docker: see [Environment variables](#environment-variables) for keeping your own). Variants for Active Directory and OpenLDAP are shown; this is a minimal config, see the [django-auth-ldap documentation](https://django-auth-ldap.readthedocs.io) for more.

The Docker image includes the LDAP packages. On an installer or manual install, add them to the virtualenv first; pip builds `python-ldap` against these headers:

```bash
apt-get -y install libldap2-dev libsasl2-dev   # Ubuntu / Debian
dnf -y install openldap-devel cyrus-sasl-devel   # RHEL / Rocky / AlmaLinux
zypper --non-interactive install -y openldap2-devel cyrus-sasl-devel   # openSUSE
/srv/webvirtcloud/venv/bin/pip3 install -r /srv/webvirtcloud/conf/requirements-ldap.txt
```

Enable the LDAP backend:

```bash
sudo sed -i "s~#\"django_auth_ldap.backend.LDAPBackend\",~\"django_auth_ldap.backend.LDAPBackend\",~g" /srv/webvirtcloud/webvirtcloud/settings.py
```

Set the LDAP server and bind DN:

```python
# Active Directory
AUTH_LDAP_SERVER_URI = "ldap://example.com"
AUTH_LDAP_BIND_DN = "username@example.com"
AUTH_LDAP_BIND_PASSWORD = "password"

# OpenLDAP
AUTH_LDAP_SERVER_URI = "ldap://example.com"
AUTH_LDAP_BIND_DN = "cn=username,ou=users,dc=example,dc=com"
AUTH_LDAP_BIND_PASSWORD = "password"
```

Set the user and group search base and filter:

```python
# Active Directory
AUTH_LDAP_USER_SEARCH = LDAPSearch(
    "CN=Users,DC=example,DC=com", ldap.SCOPE_SUBTREE, "(sAMAccountName=%(user)s)"
)
AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    "CN=Users,DC=example,DC=com", ldap.SCOPE_SUBTREE, "(objectClass=group)"
)
AUTH_LDAP_GROUP_TYPE = NestedActiveDirectoryGroupType()

# OpenLDAP
AUTH_LDAP_USER_SEARCH = LDAPSearch(
    "ou=users,dc=example,dc=com", ldap.SCOPE_SUBTREE, "(uid=%(user)s)"
)
AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    "ou=groups,dc=example,dc=com", ldap.SCOPE_SUBTREE, "(objectClass=groupOfUniqueNames)"
)
AUTH_LDAP_GROUP_TYPE = GroupOfUniqueNamesType()  # import needs to be changed at the top of settings.py
```

Set the group required to access WebVirtCloud (`False` disables this filter):

```python
AUTH_LDAP_REQUIRE_GROUP = "CN=WebVirtCloud Access,CN=Users,DC=example,DC=com"
```

Populate user fields from LDAP:

```python
AUTH_LDAP_USER_FLAGS_BY_GROUP = {
    "is_staff": "CN=WebVirtCloud Staff,CN=Users,DC=example,DC=com",
    "is_superuser": "CN=WebVirtCloud Admins,CN=Users,DC=example,DC=com",
}
AUTH_LDAP_USER_ATTR_MAP = {
    "first_name": "givenName",
    "last_name": "sn",
    "email": "mail",
}
```

An LDAP user is authenticated by LDAP and authorized through the WebVirtCloud permissions. To move a user from LDAP to WebVirtCloud, change its password in the UI and remove it from the LDAP group.

### Two-factor login (OTP)

Set `OTP_ENABLED = True` in `settings.py` to ask for a one-time code at login. It is per user: a user without a confirmed device signs in with the password alone.

The QR code is mailed as a link to a page that shows it, good for one hour: the mail does not hold the code's secret. Email OTP QR code on a user's page (Users) sends it; Lost OTP? on the login page sends it to an enrolled user who gives their address.

### Serial console

A VM without graphics (no `<graphics>` device, a `<console type='pty'>`) opens a serial console (xterm.js) instead of VNC. It is off by default. To turn it on, set `WEBVIRTCLOUD_SERIAL_CONSOLE=1` (Docker: in `docker-compose.override.yml`, then `docker compose up -d`) or `SERIAL_CONSOLE_ENABLED = True` in `settings.py` and `systemctl restart webvirt-cloud webvirt-socketiod`.

- The VM page's Settings → Console switches a shut-off VM between VNC and serial (Console type). A new VNC console takes the form's other fields; on a TCP or TLS compute it needs Listen on: All interfaces (SSH and socket computes reach a localhost console).
- The guest must use its serial port: a login prompt needs `systemctl enable --now serial-getty@ttyS0`, boot messages need the kernel parameter `console=ttyS0,115200`. The console shows only what the guest writes after it opens; press Enter for a new prompt.
- socketiod listens on 127.0.0.1:6081; the page reaches it through nginx's `/socket.io/` location on the panel's own address.
- It accepts the console page's signed token, as noVNC does: whoever gets that token within 120 s gets the console. An open console closes within 10 s once its user loses access to the VM.
- One console per VM, at most 20 at a time; a second one is refused with the reason, except a superuser's, which takes the console over.
- novncd and socketiod log to the journal (`journalctl -u webvirt-novncd -u webvirt-socketiod`) or, in Docker, to `docker logs`: a console that was refused or could not connect says why there.

## Backups

The panel backs itself up every day at 03:15 (cron in Docker, `webvirt-backup.timer` otherwise) into a new directory under `/srv/webvirtcloud/backups`, in Docker the `webvirtcloud-backups` volume, and keeps the newest 7. A backup holds:

- `db.sqlite3`: a consistent copy taken while the panel runs, checked with `PRAGMA integrity_check`; with PostgreSQL it is left out, so back up that database yourself
- `secret_key`, `node_id` and `settings.py`
- `ssh/`: the SSH keys of the panel's user, which the SSH computes accept
- `pki/`: the TLS client certificates of the panel's user, which the TLS computes accept
- `commit`, outside Docker

The database holds compute passwords and keys: the directories are readable only by the panel's user. They are on the same host as the panel; the [off-site copy](#off-site-copy) keeps them on another server too. A failed backup is reported in `docker logs` or by `systemctl status webvirt-backup` and deletes no older backup.

Take one now:

```bash
docker compose exec webvirtcloud /sbin/setuser www-data venv/bin/python3 manage.py backup   # Docker
systemctl start webvirt-backup && journalctl -u webvirt-backup -n 3                          # otherwise
```

To restore one, follow [Restore and rollback](#restore-and-rollback) with `b` set to its directory. In Docker, copy it out of the volume first (`docker compose cp webvirtcloud:/srv/webvirtcloud/backups/webvirtcloud-backup-YYYYMMDD-HHMMSS ..`) and leave out the `git checkout` and `build` lines: the backup has no commit. To move the panel to a new machine, see [Moving to a new machine](#moving-to-a-new-machine).

### Off-site copy

`webvirt-offsite.timer` copies the backups every day at 03:45 with [restic](https://restic.net) over SFTP to another server, encrypted with a password that only you and the panel's host hold, and keeps 7 daily, 4 weekly and 6 monthly copies there. It runs on the panel's host as root, also with Docker. It fails, and `journalctl -u webvirt-offsite` says why, when the newest backup is older than 26 hours or the copy does not finish.

On the other server, create the user the copies go to (`wvcbackup` on `backup.example.com` below):

```bash
useradd -m wvcbackup && install -d -o wvcbackup -m 700 ~wvcbackup/.ssh
```

On the panel's host, from a root shell in the panel's checkout (`/srv/webvirtcloud`, or the clone Docker runs from):

1. Install restic and curl (RHEL: `dnf -y install epel-release && dnf -y install restic`, openSUSE: `zypper -n install restic curl`) and the job:

   ```bash
   apt-get -y install restic curl
   install -m 755 conf/webvirt-offsite.sh /usr/local/sbin/webvirt-offsite
   cp conf/systemd/webvirt-offsite.service conf/systemd/webvirt-offsite.timer /etc/systemd/system/
   ```

2. Give the host a key of its own for the other server:

   ```bash
   install -d -m 700 /root/.ssh
   ssh-keygen -q -t ed25519 -N '' -f /root/.ssh/webvirtcloud-offsite
   cat >> /root/.ssh/config <<'EOF'
   Host webvirtcloud-offsite
     HostName backup.example.com
     User wvcbackup
     IdentityFile /root/.ssh/webvirtcloud-offsite
   EOF
   ```

   Add `/root/.ssh/webvirtcloud-offsite.pub` to `~wvcbackup/.ssh/authorized_keys` on the other server (owned by `wvcbackup`, mode 600), then connect once to record the server's key:

   ```bash
   ssh -o StrictHostKeyChecking=accept-new webvirtcloud-offsite true
   ```

3. Write the settings with a new password and create the repository. With Docker, set `WVC_BACKUPS` to the volume, `$(docker volume inspect -f '{{.Mountpoint}}' webvirtcloud_webvirtcloud-backups)`. `WVC_HEARTBEAT` is optional: a URL called after each good copy, such as a [healthchecks.io](https://healthchecks.io) check, which tells you when a day passes without one.

   ```bash
   install -m 600 /dev/null /etc/webvirtcloud-offsite.env
   cat > /etc/webvirtcloud-offsite.env <<EOF
   RESTIC_REPOSITORY=sftp:webvirtcloud-offsite:restic
   RESTIC_PASSWORD=$(head -c 30 /dev/urandom | base64)
   WVC_BACKUPS=/srv/webvirtcloud/backups
   WVC_HEARTBEAT=
   EOF
   (set -a && . /etc/webvirtcloud-offsite.env && restic init)
   ```

   Keep `RESTIC_REPOSITORY`, `RESTIC_PASSWORD` and the server's address in your password manager: without the password nobody can read the copies, you included.

4. Start it and take the first copy:

   ```bash
   systemctl daemon-reload && systemctl enable --now webvirt-offsite.timer &&
   systemctl start webvirt-offsite && journalctl -u webvirt-offsite -n 5
   ```

To get a backup back when the panel's host is lost, give the new host a key as in step 2, then:

```bash
read -rs RESTIC_PASSWORD && export RESTIC_PASSWORD RESTIC_REPOSITORY=sftp:webvirtcloud-offsite:restic
restic snapshots --tag webvirtcloud
restic restore latest --tag webvirtcloud --target /root/offsite-restore
b=$(find /root/offsite-restore -type d -name 'webvirtcloud-backup-*' | sort | tail -n 1)
```

and follow [Moving to a new machine](#moving-to-a-new-machine) with that `b` (leave out its `b=` line).

## Updating

Every update starts with a backup in its own directory (mode 700, named by date) that holds the database, the commit it was taken from and, for installer and manual installations, `settings.py`, the nginx config, `/etc/default/webvirtcloud` if there is one and migrations an old installer generated (`local-migrations.tar`). The database is copied with SQLite's backup API, which also finishes a write interrupted by a crash. This covers sqlite only; with PostgreSQL (`WEBVIRTCLOUD_DB_HOST`), back up that database yourself before updating.

### Docker

Each new container builds `settings.py` from the template and runs the migrations at start; the database and the secret key stay in the `webvirtcloud-data` volume. Keep your settings in `docker-compose.override.yml` (at least `ALLOWED_HOSTS`, see [Docker](#docker)).

Run the commands in the directory you installed from. Compose names the deployment after that directory (`webvirtcloud`), so another clone in a directory of the same name acts on the same containers and volumes.

```bash
cd webvirtcloud &&
b=../webvirtcloud-backup-$(date +%Y%m%d-%H%M%S) &&
mkdir -m 700 "$b" && git rev-parse HEAD > "$b/commit" &&
git checkout master && git pull &&
docker compose build &&
docker compose stop -t 95 &&
docker compose run --rm --no-deps -T --entrypoint /srv/webvirtcloud/venv/bin/python3 webvirtcloud \
  -c "import sqlite3,sys,tempfile; t=tempfile.mktemp(); sqlite3.connect('data/db.sqlite3').backup(sqlite3.connect(t)); sys.stdout.buffer.write(open(t,'rb').read())" > "$b/db.sqlite3.part" &&
mv "$b/db.sqlite3.part" "$b/db.sqlite3" &&
docker compose up -d
```

### Moving from supervisor to systemd

Versions up to v3.0.0 ran the panel under supervisor. Once, before the update steps below, stop it there, keep its config and remove it:

```bash
supervisorctl stop webvirtcloud novncd socketiod webvirt-worker
mv /etc/supervisor/conf.d/webvirtcloud.conf /root/webvirtcloud-supervisor.conf   # Debian / Ubuntu
mv /etc/supervisord.d/webvirtcloud.ini /root/webvirtcloud-supervisor.conf        # RHEL / openSUSE
supervisorctl update
```

Move the `environment=` values of that config into `/etc/default/webvirtcloud` (root, mode 600), one `NAME='value'` per line; leave out the worker's `WEBVIRTCLOUD_LOG_FILE`. Step 4 installs and starts the systemd units. Remove supervisor once nothing else uses it; a compute moves gstfsd as in [Adding a Compute Node](#adding-a-compute-node), step 3.

### Installer and manual installation

`git pull` never overwrites `webvirtcloud/settings.py` or `/etc/nginx/conf.d/webvirtcloud.conf`; steps 2 and 4 bring them up to date. Run the steps from a root shell; they use `$b`, so in a new shell set it again to the backup directory.

1. Stop the panel, back up and pull:

   ```bash
   systemctl stop webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
   # once: root may use the repo, which belongs to the service user
   git config --global --add safe.directory /srv/webvirtcloud
   b=/root/webvirtcloud-backup-$(date +%Y%m%d-%H%M%S)
   cd /srv/webvirtcloud &&
   ! systemctl is-active --quiet webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker &&
   mkdir -m 700 "$b" &&
   venv/bin/python3 -c "import sqlite3,sys; sqlite3.connect('db.sqlite3').backup(sqlite3.connect(sys.argv[1]))" "$b/db.sqlite3.part" &&
   mv "$b/db.sqlite3.part" "$b/db.sqlite3" &&
   cp -p webvirtcloud/settings.py /etc/nginx/conf.d/webvirtcloud.conf "$b"/ &&
   { [ ! -f /etc/default/webvirtcloud ] || cp -p /etc/default/webvirtcloud "$b"/; } &&
   git rev-parse HEAD > "$b/commit" &&
   git ls-files -z --others --exclude-standard -- '*/migrations/*.py' | tar --null -T - --remove-files -cf "$b/local-migrations.tar" &&
   git checkout -- $(git ls-files -m -- static dev/scss install.sh webvirtcloud.sh) &&
   git checkout master && git pull
   ```

   Older installers collected static files into the tracked `static/` and deleted the tracked `install.sh` and `webvirtcloud.sh`; the second-to-last line puts those files back, so that `git pull` can update them.

2. Rebuild `settings.py` from the template (the file keeps its owner and mode), then put back your own values; the `diff` lists them:

   ```bash
   cat webvirtcloud/settings.py.template > webvirtcloud/settings.py
   diff "$b/settings.py" webvirtcloud/settings.py
   ```

   Typical ones are `TIME_ZONE`, `WS_*`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and LDAP. Two need care:
   - a literal `SECRET_KEY = "..."` (older installers wrote it there): put the value into `data/secret_key` instead (`mkdir -p data` first if there is no `data/`). With no key, `migrate` in step 3 stops with "The SECRET_KEY setting must not be empty" and every page fails; with another key, every user is signed out;
   - `SHOW_PROFILE_EDIT_PASSWORD`: keep it for this one `migrate` if you have it (migration `accounts.0008` reads it), then delete it.

3. Install, migrate, and fix ownership and modes (`nginx:nginx` instead of `www-data:www-data` on RHEL / openSUSE). With LDAP, also run `venv/bin/pip3 install -U -r conf/requirements-ldap.txt` (headers: [LDAP](#ldap)):

   ```bash
   venv/bin/pip3 install -U -r conf/requirements.txt &&
   { ! tar -tf "$b/local-migrations.tar" | grep -qx accounts/migrations/0006_alter_userattributes_id_alter_userinstance_id_and_more.py ||
     venv/bin/python3 manage.py migrate accounts 0005 --fake; } &&
   venv/bin/python3 manage.py migrate &&
   venv/bin/python3 manage.py collectstatic --noinput &&
   chown -R www-data:www-data /srv/webvirtcloud &&
   chmod -R go-rwx data webvirtcloud/settings.py db.sqlite3
   ```

   Installers from before September 2025 generated migrations of their own; step 1 moved them into `local-migrations.tar`. One of them has the name of a tracked migration, which `migrate` would skip; the second line marks it unapplied so that the tracked one runs.

4. Update the nginx config the same way as `settings.py`:

   ```bash
   cp conf/nginx/webvirtcloud.conf /etc/nginx/conf.d/webvirtcloud.conf
   diff "$b/webvirtcloud.conf" /etc/nginx/conf.d/webvirtcloud.conf
   ```

   Put back your own lines (`server_name`, TLS, the noVNC port). Install the systemd units; your own service settings stay in `/etc/default/webvirtcloud` and in drop-ins. Debian / Ubuntu:

   ```bash
   cp conf/systemd/webvirt-{cloud,novncd,socketiod,worker,backup}.service conf/systemd/webvirt-backup.timer /etc/systemd/system/
   ```

   RHEL / openSUSE:

   ```bash
   for u in cloud novncd socketiod worker backup; do sed 's/^\(User\|Group\)=.*/\1=nginx/' conf/systemd/webvirt-$u.service > /etc/systemd/system/webvirt-$u.service; done
   cp conf/systemd/webvirt-backup.timer /etc/systemd/system/
   ```

   Then reload nginx and start the panel:

   ```bash
   nginx -t && systemctl reload nginx && systemctl daemon-reload && systemctl enable --now webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker webvirt-backup.timer
   ```

Older versions collected static files into `static/`; `git clean -n static/` lists the leftovers, which can be deleted.

### Restore and rollback

Restoring puts back the database as it was at the backup; changes made since are lost. Migrations are not reversed. This covers sqlite; restore a PostgreSQL database from your own backup before rolling back the code. Set `b` to the backup directory to restore. To restore the database without rolling back the code, leave out the `git checkout` and `build` lines.

Docker, in the directory you installed from:

```bash
cd webvirtcloud &&
b=../webvirtcloud-backup-YYYYMMDD-HHMMSS &&
docker compose stop -t 95 &&
docker compose run --rm --no-deps -T --entrypoint /srv/webvirtcloud/venv/bin/python3 webvirtcloud \
  -c "import os,sqlite3,sys,tempfile; t=tempfile.mktemp(); open(t,'wb').write(sys.stdin.buffer.read()); [os.remove(p) for p in ('data/db.sqlite3-journal','data/db.sqlite3-wal','data/db.sqlite3-shm') if os.path.exists(p)]; sqlite3.connect(t).backup(sqlite3.connect('data/db.sqlite3'))" < "$b/db.sqlite3" &&
git checkout "$(cat "$b/commit")" &&
docker compose build &&
docker compose up -d    # the container fixes ownership and modes at start
```

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
cp "$b/settings.py" webvirtcloud/settings.py &&
{ [ ! -f "$b/webvirtcloud.conf" ] || cp "$b/webvirtcloud.conf" /etc/nginx/conf.d/webvirtcloud.conf; } &&
venv/bin/pip3 install -r conf/requirements.txt &&
venv/bin/python3 manage.py collectstatic --noinput &&
chown -R www-data:www-data /srv/webvirtcloud &&
chmod 600 db.sqlite3 webvirtcloud/settings.py
```

Put back `/etc/default/webvirtcloud` if the backup has it (`cp -p "$b/webvirtcloud" /etc/default/`), then reload nginx and start the panel:

```bash
nginx -t && systemctl reload nginx && systemctl start webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
```

A version from before v3.0.0 has no worker: `systemctl disable --now webvirt-worker`. A rollback keeps the systemd units. A rollback leaves the clone on a detached HEAD at the restored commit; the update steps record that commit before they switch back to `master`.

### Moving to a new machine

A [backup](#backups) moves the panel to a new machine, or back onto lost volumes: the database, the secret key (signed-in users stay signed in), the worker's id and the SSH keys and TLS certificates the computes accept. Install the panel there first, the same version or a newer one, then copy the backup directory over and set `b` to it. The backup does not hold `docker-compose.override.yml`, the nginx config or `/etc/default/webvirtcloud`: bring your own lines over yourself. Users sign in with their passwords from the backup; the new installation's `data/admin_password` no longer applies. A `SECRET_KEY` set in the compose file has no `secret_key` in the backup: set the same value on the new machine. With PostgreSQL, stop the old panel before the new one starts: both would run the jobs of the one database.

Docker, in the directory you installed from:

```bash
cd webvirtcloud &&
b=../webvirtcloud-backup-YYYYMMDD-HHMMSS &&
docker compose stop -t 95 &&
docker compose run --rm --no-deps -T --entrypoint /srv/webvirtcloud/venv/bin/python3 webvirtcloud \
  -c "import os,sqlite3,sys,tempfile; t=tempfile.mktemp(); open(t,'wb').write(sys.stdin.buffer.read()); [os.remove(p) for p in ('data/db.sqlite3-journal','data/db.sqlite3-wal','data/db.sqlite3-shm') if os.path.exists(p)]; sqlite3.connect(t).backup(sqlite3.connect('data/db.sqlite3'))" < "$b/db.sqlite3" &&
{ [ ! -f "$b/secret_key" ] || docker compose cp "$b/secret_key" webvirtcloud:/srv/webvirtcloud/data/; } &&
docker compose cp "$b/node_id" webvirtcloud:/srv/webvirtcloud/data/ &&
{ [ ! -d "$b/ssh" ] || docker compose cp "$b/ssh/." webvirtcloud:/var/www/.ssh/; } &&
{ [ ! -d "$b/pki" ] || docker compose cp "$b/pki/." webvirtcloud:/var/www/.pki/; } &&
docker compose up -d    # the container migrates and fixes ownership and modes at start
```

Installer and manual installation, from a root shell (`nginx` instead of `www-data` on RHEL / openSUSE). Compare `$b/settings.py` with `webvirtcloud/settings.py` and carry your own values over:

```bash
b=/root/webvirtcloud-backup-YYYYMMDD-HHMMSS
systemctl stop webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
cd /srv/webvirtcloud &&
venv/bin/python3 -c "import os,sqlite3,sys; [os.remove(p) for p in ('db.sqlite3-journal','db.sqlite3-wal','db.sqlite3-shm') if os.path.exists(p)]; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect('db.sqlite3'))" "$b/db.sqlite3" &&
cp "$b/node_id" data/ && { [ ! -f "$b/secret_key" ] || cp "$b/secret_key" data/; } &&
mkdir -p ~www-data/.ssh && { [ ! -d "$b/ssh" ] || cp "$b"/ssh/* ~www-data/.ssh/; } &&
mkdir -p ~www-data/.pki && { [ ! -d "$b/pki" ] || cp -r "$b"/pki/. ~www-data/.pki/; } &&
venv/bin/python3 manage.py migrate &&
chown -R www-data:www-data data ~www-data/.ssh ~www-data/.pki &&
chmod 700 data ~www-data/.ssh ~www-data/.pki && chmod 600 db.sqlite3 &&
systemctl start webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker
```

### Behavior changes

What an update from an older version changes for operators and users:

- Requests for a host not in `ALLOWED_HOSTS` get 400. The installer writes the server's names and IPs; add more with the `ALLOWED_HOSTS` env var. The cloud-init datasource host must be allowed too.
- Logging out needs a POST; a GET to `/accounts/logout/` gets 405.
- The API accepts only a session from the login form or an API token (no HTTP Basic), and the API docs need a login. Sessions opened through the old password-only doors skip OTP; end them once after the update (everyone signs in again): `python3 manage.py shell -c "from django.contrib.sessions.models import Session; Session.objects.all().delete()"`.
- Failed logins lock a user (django-axes). The limit and lock time are on the Settings page; unlock with `python3 manage.py axes_reset_username <username>`.
- Changing one's own password is the "Can change password" permission (per user or group; new users have it); `SHOW_PROFILE_EDIT_PASSWORD` is gone.
- The admin's first-login password change survives losing `data/admin_password` (migration `accounts.0007`); run `migrate` as a user who can read that file.
- An `admin` account that still has the password `admin` (the first user of versions up to v2.0.0) must change it at its next login, and its API tokens are refused until then (migration `accounts.0013`).
- A `settings.py` kept from an older version must match the template (apps, middleware, the SQLite `OPTIONS`, the REST framework, knox, axes and password settings): rebuild it from the template and carry your own values over, as step 2 of the update does.
- The VNC console connects to `/novncd/` on the panel's own address through nginx, and the serial console to `/socket.io/`: they work on HTTPS and behind another proxy without settings. `WS_PUBLIC_PORT`, `WS_PUBLIC_HOST`, `WS_PUBLIC_PATH`, `WS_CERT` and `SOCKETIO_PUBLIC_HOST`/`_PORT`/`_PATH` are gone; remove them from `docker-compose.override.yml`, `/etc/default/webvirtcloud` or a kept `settings.py`, set `WS_HOST = "127.0.0.1"` in a kept `settings.py`, and close port 6080 in the firewall.
- Installer and manual installations run the panel as systemd units (`webvirt-cloud`, `webvirt-novncd`, `webvirt-socketiod`, `webvirt-worker`, `webvirt-backup.timer`) and computes run `webvirt-gstfsd`, instead of supervisor; see [Moving from supervisor to systemd](#moving-from-supervisor-to-systemd). Service settings go into `/etc/default/webvirtcloud`, service output into the journal (`journalctl -u webvirt-cloud`); the app log stays in `data/`. novncd and socketiod run sandboxed (read-only system directories, no `/home`).
- gstfsd does only what the panel signs with the host's key: it does not start without `GSTFSD_KEY` in `/etc/default/webvirt-gstfsd`. On every compute, update gstfsd and its unit and make the key as in [Adding a Compute Node](#adding-a-compute-node), step 3 (a remote panel's `GSTFSD_BIND_HOST` and `GSTFSD_ALLOW_REMOTE` move into that file from `systemctl edit webvirt-gstfsd`), then enter the key on each compute's edit page.
- LDAP login's packages are in `conf/requirements-ldap.txt` and no longer installed by default, nor their build headers by the installer; the Docker image keeps them. An existing virtualenv keeps them, but only installing that file updates them (see [LDAP](#ldap)).
- The themes ship compiled; picking one on the Settings page only saves its name, and the "Theme SASS Path" setting is gone. Browsers revalidate static files on each load: files cached before the update can stay until a hard reload (Ctrl+F5) of each page; an external caching proxy may need a purge.
- The panel backs itself up every day ([Backups](#backups)); in Docker into a new volume, `webvirtcloud-backups`.
- New passwords must pass Django's password validators: at least 8 characters, not a common password, not only digits, not like the user's name or e-mail. Existing passwords keep working.
- In Docker, the TLS client certificates of TLS computes are kept in a new volume, `webvirtcloud-pki` (`/var/www/.pki`), and backed up; put them there once ([Adding a Compute Node](#adding-a-compute-node), step 2).
- The SQLite database must be on a local file system (WAL). Outside compose, stop the Docker container with `docker stop -t 95` so the worker can finish running jobs.
- Long operations run as jobs in a worker process (`manage.py run_worker`): creating, cloning, migrating and deleting VMs, moving disks, cloning volumes, taking and reverting snapshots and deleting external snapshots. The page returns at once and the job panel and the Jobs page follow them; a migration can be cancelled. The API's VM create, migrate and delete answer 202 with the job and need a new `submission_key` per request. The create form no longer takes a console password; set it on the VM page.
- An ISO upload is tracked as a job that can be cancelled. The browser sends the file, so stay on the page until it ends; an upload left idle for an hour is ended and its partial file deleted.
- A clone of a running VM (libvirt 11.10 or later, local file disks, no TPM) locks the VM until the copy ends and can be cancelled; cancelling a clone of a shut-off VM has no effect. A job that ends uncertain keeps its VM locked until a superuser resolves it on its job page.
- The job worker runs at most half of its concurrency (Settings, at least one) of one host's jobs at a time, so a host that does not answer cannot take every slot.
- A new VM is made in three steps (host, machine, details) on one form; flavors are presets that fill vCPU, memory and disk size. "VM Clone Auto Migrate" is removed; a clone stays on its source host.
- A user's quota counts, for each VM, the larger of its running and its next-start vCPUs, memory and disks, and a queued clone as one VM. A user can be over the quota after the update; nothing is stopped, but new VMs, clones and raises are refused until it fits.
- A user who is not a superuser names a clone with one of the free names the clone form offers; other names are refused.
- A template VM is changed or deleted only by superusers and staff owners with the matching permission; other owners can still view, open the console and clone it.
- On a running VM the edit forms show the settings as they will be at the next start, so saving an edit no longer reverts another pending change.
- External snapshots need libvirt 9.9 or newer on the computes. libvirt 9.10 (openEuler 24.03 LTS) refuses to revert a snapshot taken without memory of a running or paused VM ("Invalid target domain state 'disk-snapshot'"); 11.10 reverts it. A VM's snapshots form one chain: after a revert, delete the newer snapshots before taking another. An internal snapshot is reverted only on a shut-off VM. Snapshot names no longer get an `s1.` prefix. A snapshot an older version took of a UEFI VM can only be deleted, not reverted. On NFS, the qemu user needs write access to the image directory to remove merged snapshot files.
- A storage volume a VM still needs (a disk, a backing file or a snapshot's file) is not deleted; deleting a VM with its files keeps a file another compute's VM or volume uses at the same path, and is refused before the VM is stopped when one of the other computes cannot be reached.
- A VM that vanishes from its compute, or whose compute is deleted, keeps its owners for `INSTANCE_OWNERSHIP_RETENTION_DAYS` (30) in case the same UUID comes back; superusers manage these records on the "Removed VMs" page.
- The Logs page records who changed what (computes, users, groups, VM owners, settings, SSH keys, host networks, pools, volumes, interfaces, secrets and network filters), every login, failed login and lockout, and every page or API call refused to a signed-in user or an API token, with the address and the result.
- On a host whose libvirt cannot change network interfaces (the udev backend: RHEL 9 and later, Debian 12), the interface pages offer no create, start, stop or delete.
- The panel is offered in English, Turkish and Simplified Chinese.
- With SELinux (RHEL family, openEuler), systemd could not run the virtualenv's programs and the panel did not start. The installer now writes file context rules (`httpd_sys_content_t` for the panel, `bin_t` for `venv/bin`) instead of `chcon`, so a relabel keeps them. A manual installation runs `semanage fcontext -a -t bin_t "/srv/webvirtcloud/venv/bin(/.*)?"` and `restorecon -R /srv/webvirtcloud` once; an installer one runs the installer again.

## Usage

### Users, Roles and Permissions

See [doc/permissions.md](doc/permissions.md).

### REST API

The REST API (Django REST Framework, documented with `drf-spectacular`) takes the login session or an API token. After logging in:

* **Swagger UI:** `http://<server>/swagger/`
* **ReDoc UI:** `http://<server>/redoc/`
* **OpenAPI 3.0 schema:** `http://<server>/api/schema/` (JSON or YAML)
* **API tokens**, for scripts and tools: **Profile → API Tokens**. A token acts as its user and is shown once; send it as a header:

  ```bash
  curl -H "Authorization: Token wvc_..." https://<server>/api/v1/instances/
  ```

### Screenshots

| VM list | VM page |
|:---:|:---:|
| ![VM list](doc/images/instances.png) | ![VM page](doc/images/instance.png) |

| Computes | Host overview |
|:---:|:---:|
| ![Computes](doc/images/computes.png) | ![Host overview](doc/images/overview.png) |

| New VM | Logs |
|:---:|:---:|
| ![New VM](doc/images/create.png) | ![Logs](doc/images/logs.png) |

## Development

Run every step as your normal user, not with `sudo`: if `manage.py` ever runs as root, `db.sqlite3` and `data/` end up root-owned and later runs fail with "readonly database" or "Permission denied".

1. System packages. The virtualenv reuses the distro's `libvirt`, `lxml` and `ldap` bindings when their versions satisfy `conf/requirements.txt`; otherwise pip installs or builds newer ones:

   ```bash
   # Rocky Linux / RHEL / Fedora
   sudo dnf -y install git python3-devel libvirt-devel python3-libvirt python3-lxml python3-ldap gcc

   # Ubuntu / Debian
   sudo apt-get update && sudo apt-get -y install git python3-venv python3-dev python3-lxml python3-libvirt python3-ldap libvirt-dev zlib1g-dev libldap2-dev libsasl2-dev gcc pkg-config

   # openSUSE Leap 15.x / Tumbleweed / SLES 15 (use python3.11 instead of python3 below)
   sudo zypper --non-interactive install -y git hostname python311 python311-devel python311-pip python311-libvirt-python python311-lxml python311-ldap libvirt-devel openldap2-devel cyrus-sasl-devel libopenssl-devel gcc pkg-config
   ```

2. Virtualenv and dependencies (`--system-site-packages` is required to see the distro bindings; `dev/requirements.txt` includes `conf/requirements.txt`):

   ```bash
   python3 -m venv --system-site-packages .venv
   source .venv/bin/activate
   pip install -r dev/requirements.txt
   ```

3. Settings and secret key:

   ```bash
   cp webvirtcloud/settings.py.template webvirtcloud/settings.py
   mkdir -p data && python conf/runit/secret_generator.py > data/secret_key && chmod 600 data/secret_key
   ```

4. Migrate and run the dev server (`settings-dev` enables `DEBUG` and the Django Debug Toolbar); the admin password is in `data/admin_password`, or set `ADMIN_PASSWORD` beforehand:

   ```bash
   python manage.py migrate
   python manage.py runserver 0.0.0.0:8000 --settings=webvirtcloud.settings-dev
   ```

   Open `http://127.0.0.1:8000`. The browser consoles connect to `/novncd/` and `/socket.io/` on the panel's own address, which the dev server does not proxy: try them in the Docker image, or behind nginx with `conf/nginx/webvirtcloud.conf`.

### Keyboard layouts

The VNC console's "Type it" sends the keys that type each character on the VM's keyboard layout. A layout is one file in `console/layouts/`, written from the XKB layout of the same name (needs `libxkbcommon` and `xkeyboard-config`, present on Linux desktops):

```bash
python3 dev/console_layout.py de "German"                  # XKB layout, the name the console shows
python3 dev/console_layout.py tr "Turkish F" --variant f   # a variant
python3 dev/console_layout.py us "English (US)" --model pc104  # a keyboard without the key left of Z
```

It lists the dead keys it leaves out: a character only a dead key types cannot be typed. Type a sample with every character group of the layout into a VM set to that layout before committing the file.

### Translations

The panel is translated into the languages of `LANGUAGES` in `settings.py`, each with a full catalog in `locale/`. A new or changed text needs its translation in each before CI passes (needs `gettext`):

```bash
python manage.py makemessages -l tr -l zh --no-obsolete --ignore=staticfiles --ignore=.venv
# translate the new and fuzzy entries of locale/tr/LC_MESSAGES/django.po and locale/zh/LC_MESSAGES/django.po
python manage.py compilemessages -l tr -l zh
```

### Running tests

```bash
python manage.py test   # all tests, including vrtManager
ruff check .
```

Each app keeps its tests in a `tests/` package, and the tests of the libvirt layer are in `vrtManager/tests`, so `python manage.py test instances` runs one app; `--parallel` spreads the tests over the CPUs. The suite includes mocked regression tests and disk/clone tests on libvirt's in-process `test:///default` driver. Set `WEBVIRTCLOUD_DB_HOST` (and the other `WEBVIRTCLOUD_DB_*` variables) to run it against PostgreSQL, as CI does.

The compute and instance tests run only when `TEST_LIBVIRT_HOST` is set, never on the machine's own libvirt by default. A green result with skips does not establish live KVM compatibility. The instance tests create `wvc-test-*` VMs and a temporary `wvc-test` pool (`/var/lib/libvirt/wvc-test`), remove them afterwards, and fail if any other VM or volume on the host changed:

```bash
export TEST_LIBVIRT_HOST=compute1 TEST_LIBVIRT_TYPE=2   # 1 TCP, 2 SSH, 3 TLS, 4 socket
export TEST_LIBVIRT_LOGIN=root TEST_LIBVIRT_PASSWORD=   # login/password for TCP and TLS
export TEST_LIBVIRT_GUEST_IMAGE=/var/lib/libvirt/images/linux.qcow2   # optional, see below
export TEST_LIBVIRT_LVM_DEVICE=/dev/vdb   # optional: an empty disk of 4 GiB or more on the host, wiped by the LVM tests
export TEST_LIBVIRT_ISCSI_TARGET=iqn.2026-10.test.wvc:lun   # optional: a target on the host's 127.0.0.1, open to any initiator, with a LUN
export TEST_LIBVIRT_NFS_EXPORT=/srv/wvc-nfs   # optional: a directory the host exports to its 127.0.0.1 over NFS
python manage.py test
```

`TEST_LIBVIRT_GUEST_IMAGE` enables the tests that need a guest OS (disk and NIC hot-unplug, vCPU hotplug, guest agent, ACPI power off). It must be an installed, BIOS-bootable Linux qcow2 image with qemu-guest-agent, in a storage pool of the host other than `wvc-test`; the tests boot copies of it from overlays and only read the image. Shut down any VM using it first.

Two disposable compute nodes for these tests come from the `Vagrantfile`: AlmaLinux 10 with nested KVM, set up by `dev/libvirt-bootstrap.sh` (with this checkout's gstfsd), a SASL user for TCP (`wvc`, password `wvc-test`) and your `~/.ssh/id_ed25519.pub` for root; migration runs between them, and each has an empty second disk (`/dev/vdb`) for the LVM tests and serves a 1 GiB iSCSI LUN on 127.0.0.1 for the iSCSI test and an NFS export (`/srv/wvc-nfs`) to 127.0.0.1 for the NFS pool test. They accept TLS logins (SASL) with certificates from a throwaway CA that `vagrant up` makes in `.vagrant/tls`; the TLS run takes its client certificate from there through `HOME`. It needs Vagrant with the `vagrant-libvirt` plugin, a KVM host with `qemu-kvm` and `cyrus-sasl-md5`, and a user in the `libvirt` group. On a host that also runs Docker, let the VMs' network (the bridge of `virsh net-info vagrant-libvirt`, `virbr1` here) through Docker's forward rules (`sudo iptables -I DOCKER-USER -i virbr1 -j ACCEPT` and `sudo iptables -I DOCKER-USER -o virbr1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT`).

```bash
vagrant up --provider=libvirt
C1=$(vagrant ssh compute1 -c "hostname -I" | awk '{print $1}') C2=$(vagrant ssh compute2 -c "hostname -I" | awk '{print $1}')
for h in $C1 $C2; do ssh-keygen -R $h; ssh -o StrictHostKeyChecking=accept-new root@$h true; done   # new VMs, new host keys
export TEST_LIBVIRT_HOST=$C1 TEST_LIBVIRT_TYPE=1 TEST_LIBVIRT_LOGIN=wvc TEST_LIBVIRT_PASSWORD=wvc-test
export TEST_LIBVIRT_SSH_HOST=$C2 TEST_LIBVIRT_SSH_LOGIN=root TEST_LIBVIRT_MIGRATE_ADDRESS=$C2 TEST_LIBVIRT_LVM_DEVICE=/dev/vdb TEST_LIBVIRT_ISCSI_TARGET=iqn.2026-10.test.wvc:lun TEST_LIBVIRT_NFS_EXPORT=/srv/wvc-nfs
python manage.py test
HOME=$PWD/.vagrant/tls TEST_LIBVIRT_TYPE=3 TEST_LIBVIRT_SSH_HOST= python manage.py test   # compute1 again, over TLS
# a socket compute is the panel's own libvirt: the committed HEAD runs inside compute1
git archive HEAD | vagrant ssh compute1 -c "sudo sh -c 'rm -rf /root/wvc && mkdir /root/wvc && tar -x -C /root/wvc'"
vagrant ssh compute1 -c "sudo -i sh -ec 'dnf -y install python3-devel openldap-devel cyrus-sasl-devel gcc; cd /root/wvc; python3 -m venv --system-site-packages venv; venv/bin/pip install -r dev/requirements.txt; cp webvirtcloud/settings.py.template webvirtcloud/settings.py; mkdir data; venv/bin/python conf/runit/secret_generator.py > data/secret_key; TEST_LIBVIRT_HOST=localhost TEST_LIBVIRT_TYPE=4 TEST_LIBVIRT_LOGIN=wvc TEST_LIBVIRT_PASSWORD=wvc-test TEST_LIBVIRT_LVM_DEVICE=/dev/vdb TEST_LIBVIRT_ISCSI_TARGET=iqn.2026-10.test.wvc:lun TEST_LIBVIRT_NFS_EXPORT=/srv/wvc-nfs venv/bin/python manage.py test'"
vagrant destroy -f
```

## License

WebVirtCloud is licensed under the [Apache Licence, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0.html).
