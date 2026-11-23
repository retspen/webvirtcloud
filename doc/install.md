# Installation

The panel runs on a virtual machine, a physical host or a KVM host itself, with Python 3.10 or newer. Install it one of three ways, then do the [first login](#first-login):

- [Installer](#installer): Ubuntu 22.04 / 24.04 / 26.04, Debian 12 / 13, RHEL / Rocky Linux / AlmaLinux / Oracle Linux 10, openEuler 24.03 LTS, openSUSE Leap 15.x / 16.0 / Tumbleweed and SLES 15
- [Docker](#docker): any host with Docker Compose
- [Manual installation](#manual-installation): the installer's systems except openEuler, step by step

## Installer

```bash
curl -fsSL -O https://raw.githubusercontent.com/retspen/webvirtcloud/master/install.sh
chmod 744 install.sh
sudo ./install.sh
```

The installer writes the server's names and IPs to `ALLOWED_HOSTS`.

Running it again:

- **Replaces** `/etc/nginx/conf.d/webvirtcloud.conf` and the systemd units: back up your own lines in the nginx config (TLS) first.
- **Keeps** `data/local_settings.py` (with its noVNC port, whatever you answer), the database, the secret key, the main nginx config, `/etc/default/webvirtcloud` and drop-ins (`systemctl edit webvirt-cloud`): put your own service settings there.

## Docker

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

The panel and its console are at `http://<server-ip>`. The database and secret key live in the `webvirtcloud-data` volume, the SSH keys in `webvirtcloud-ssh`, the TLS client certificates in `webvirtcloud-pki`, the [backups](backups.md) in `webvirtcloud-backups`. Other settings go in the same `environment:` list, see [Environment variables](configuration.md#environment-variables).

## Manual installation

Run the steps from a root shell (`sudo -i`). In step 3, replace the example `ALLOWED_HOSTS` with the names/IPs the panel (and the cloud-init datasource) is reached by.

The virtualenv is created with `--system-site-packages`: `libvirt-python` comes from the distro packages when its version satisfies `conf/requirements.txt`; otherwise pip builds it, which needs the `-dev`/`-devel` packages listed below. `lxml` is reused the same way; everything else comes from pip.

Open the steps for your system:

<details>
<summary><b>Ubuntu 22.04 / 24.04 / 26.04, Debian 12 / 13</b></summary>

```bash
# 1. System packages
apt-get update && apt-get -y install git python3-venv python3-dev python3-lxml python3-libvirt libvirt-dev zlib1g-dev libxslt1-dev nginx libsasl2-modules gcc pkg-config python3-guestfs libssl-dev

# 2. Code
git clone https://github.com/retspen/webvirtcloud /srv/webvirtcloud
cd /srv/webvirtcloud

# 3. This installation's settings (data/local_settings.py, see Configuration) and secret key
mkdir -p -m 700 data && (umask 077 &&
  echo 'ALLOWED_HOSTS += ["wvc.example.com", "192.0.2.10"]' > data/local_settings.py &&
  python3 conf/secret_generator.py > data/secret_key)

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
for g in libvirt kvm; do usermod -a -G $g www-data 2>/dev/null || true; done   # on a KVM host
chmod 700 data && chmod 600 data/local_settings.py data/secret_key && { [ ! -f db.sqlite3 ] || chmod 600 db.sqlite3; }
systemctl daemon-reload && systemctl enable --now webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker webvirt-backup.timer
nginx -t && systemctl restart nginx
```

</details>

<details>
<summary><b>RHEL / Rocky Linux / AlmaLinux / Oracle Linux 10</b></summary>

```bash
# 1. System packages (libvirt-devel is in the CRB repository)
dnf -y install epel-release && crb enable   # Rocky / AlmaLinux; on RHEL and Oracle Linux enable their CodeReady Builder repository and EPEL as their documentation says
dnf -y install git python3-devel libvirt-devel python3-libvirt python3-lxml cyrus-sasl-md5 openssl-devel glibc gcc nginx python3-libguestfs iproute-tc policycoreutils-python-utils

# 2. Code
git clone https://github.com/retspen/webvirtcloud /srv/webvirtcloud
cd /srv/webvirtcloud

# 3. This installation's settings (data/local_settings.py, see Configuration) and secret key
mkdir -p -m 700 data && (umask 077 &&
  echo 'ALLOWED_HOSTS += ["wvc.example.com", "192.0.2.10"]' > data/local_settings.py &&
  python3 conf/secret_generator.py > data/secret_key)

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
for g in libvirt kvm; do usermod -a -G $g nginx 2>/dev/null || true; done   # on a KVM host
chmod 700 data && chmod 600 data/local_settings.py data/secret_key && { [ ! -f db.sqlite3 ] || chmod 600 db.sqlite3; }
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

</details>

<details>
<summary><b>openSUSE Leap 15.x / 16.0 / Tumbleweed, SLES 15</b></summary>

On SLES 15, enable the Python 3 module and SUSE Package Hub first (`SUSEConnect -p sle-module-python3/15.7/x86_64` and `SUSEConnect -p PackageHub/15.7/x86_64`, with your service pack); the installer needs them too.

```bash
# 1. System packages (Python 3.11 stack; on Leap 16 and Tumbleweed python313-* packages and python3.13 below)
zypper --non-interactive install -y git hostname python311 python311-base python311-devel python311-pip python311-libvirt-python python311-lxml libvirt-devel libopenssl-devel gcc pkg-config nginx

# 2. Code
git clone https://github.com/retspen/webvirtcloud /srv/webvirtcloud
cd /srv/webvirtcloud

# 3. This installation's settings (data/local_settings.py, see Configuration) and secret key
mkdir -p -m 700 data && (umask 077 &&
  echo 'ALLOWED_HOSTS += ["wvc.example.com", "192.0.2.10"]' > data/local_settings.py &&
  python3.11 conf/secret_generator.py > data/secret_key)

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
for g in libvirt kvm; do usermod -a -G $g nginx 2>/dev/null || true; done   # on a KVM host
chmod 700 data && chmod 600 data/local_settings.py data/secret_key && { [ ! -f db.sqlite3 ] || chmod 600 db.sqlite3; }
systemctl daemon-reload && systemctl enable --now webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker webvirt-backup.timer
systemctl enable nginx && nginx -t && systemctl restart nginx
```

</details>

## First login

The first `migrate` creates a superuser named `admin` with a random password, written to `data/admin_password` (mode 0600):

```bash
sudo cat /srv/webvirtcloud/data/admin_password            # installer or manual installation
docker compose exec webvirtcloud cat data/admin_password   # Docker
```

Sign in at `http://<server-ip>`; you must set a new password at the first login, and the file is then deleted.

To choose the name or password yourself, set `ADMIN_USERNAME` and/or `ADMIN_PASSWORD` in the environment before that first `migrate`; a password you set is not written to the file and need not be changed.

### Lost password

[Run `manage.py`](configuration.md#running-managepy) `changepassword admin`.
