# Development

Run `manage.py` as your normal user (`sudo` only for system packages): if it ever runs as root, `db.sqlite3` and `data/` end up root-owned and later runs fail with "readonly database" or "Permission denied".

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

3. Secret key (your own settings go into [`data/local_settings.py`](doc/configuration.md#local-settings)):

   ```bash
   mkdir -p data && python conf/secret_generator.py > data/secret_key && chmod 600 data/secret_key
   ```

4. Migrate and run the dev server (`settings-dev` enables `DEBUG` and the Django Debug Toolbar); the admin password is in `data/admin_password`, or set `ADMIN_PASSWORD` beforehand:

   ```bash
   python manage.py migrate
   python manage.py runserver 0.0.0.0:8000 --settings=webvirtcloud.settings-dev
   ```

   Long operations (create, clone, migrate, delete) wait in the queue until the job worker runs; start it in another terminal with the virtualenv active:

   ```bash
   python manage.py run_worker --settings=webvirtcloud.settings-dev
   ```

   Open `http://127.0.0.1:8000`. The dev server serves the static files from `static/` while `DEBUG` is on; to try the panel with `DEBUG = False`, add `--insecure` (development only: in production nginx serves `staticfiles/`, which `collectstatic` fills). The browser consoles connect to `/novncd/` and `/socket.io/` on the panel's own address, which the dev server does not proxy: try them in the Docker image, or behind nginx with `conf/nginx/webvirtcloud.conf`.

## Keyboard layouts

The VNC console's "Type it" sends the keys that type each character on the VM's keyboard layout. A layout is one file in `console/layouts/`, written from the XKB layout of the same name (needs `libxkbcommon` and `xkeyboard-config`, present on Linux desktops):

```bash
python3 dev/console_layout.py de "German"                  # XKB layout, the name the console shows
python3 dev/console_layout.py tr "Turkish F" --variant f   # a variant
python3 dev/console_layout.py us "English (US)" --model pc104  # a keyboard without the key left of Z
```

It lists the dead keys it leaves out: a character only a dead key types cannot be typed. Type a sample with every character group of the layout into a VM set to that layout before committing the file.

## Translations

English is the source language; the panel is translated into the other languages of `LANGUAGES` in `settings.py`, each with a full catalog in `locale/`. A new or changed text needs its translation in each before CI passes (needs `gettext`):

```bash
python manage.py makemessages -l tr -l zh --no-obsolete --ignore=staticfiles --ignore=.venv
# translate the new and fuzzy entries of locale/tr/LC_MESSAGES/django.po and locale/zh/LC_MESSAGES/django.po
python manage.py compilemessages -l tr -l zh
```

## Running tests

### Local tests

```bash
python manage.py test   # all tests, including vrtManager
ruff check .
```

Each app keeps its tests in a `tests/` package, and the tests of the libvirt layer are in `vrtManager/tests`, so `python manage.py test instances` runs one app; `--parallel` spreads the tests over the CPUs. The suite includes mocked regression tests and disk/clone tests on libvirt's in-process `test:///default` driver. Set `WEBVIRTCLOUD_DB_HOST` (and the other `WEBVIRTCLOUD_DB_*` variables) to run it against PostgreSQL, as CI does.

CI tests Python 3.10–3.14 on Ubuntu (sqlite, and PostgreSQL on 3.12), the Docker image, and the installer on Ubuntu 22.04 / 24.04 / 26.04, Debian 12 / 13, AlmaLinux 10, openEuler 24.03 and openSUSE Leap 15.6 / 16.0 (`dev/test-installer.sh IMAGE` runs one of these locally).

### Live KVM tests

The compute and instance tests run only when `TEST_LIBVIRT_HOST` is set, never on the machine's own libvirt by default. A green result with skips does not establish live KVM compatibility.

- The instance tests create `wvc-test-*` VMs and a temporary `wvc-test` pool (`/var/lib/libvirt/wvc-test`), remove them afterwards, and fail if any other VM or volume on the host changed.
- **The LVM tests wipe the disk in `TEST_LIBVIRT_LVM_DEVICE`.**
- `TEST_LIBVIRT_GUEST_IMAGE` enables the tests that need a guest OS (disk and NIC hot-unplug, vCPU hotplug, guest agent, ACPI power off). It must be an installed, BIOS-bootable Linux qcow2 image with qemu-guest-agent, in a storage pool of the host other than `wvc-test`; the tests boot copies of it from overlays and only read the image. Shut down any VM using it first.

```bash
export TEST_LIBVIRT_HOST=compute1 TEST_LIBVIRT_TYPE=2   # 1 TCP, 2 SSH, 3 TLS, 4 socket
export TEST_LIBVIRT_LOGIN=root TEST_LIBVIRT_PASSWORD=   # login/password for TCP and TLS
export TEST_LIBVIRT_GUEST_IMAGE=/var/lib/libvirt/images/linux.qcow2   # optional, see above
export TEST_LIBVIRT_LVM_DEVICE=/dev/vdb   # optional: an empty disk of 4 GiB or more on the host, wiped by the LVM tests
export TEST_LIBVIRT_ISCSI_TARGET=iqn.2026-10.test.wvc:lun   # optional: a target on the host's 127.0.0.1, open to any initiator, with a LUN
export TEST_LIBVIRT_NFS_EXPORT=/srv/wvc-nfs   # optional: a directory the host exports to its 127.0.0.1 over NFS
python manage.py test
```

### Vagrant test computes

The `Vagrantfile` makes two disposable compute nodes for the live tests. It needs Vagrant with the `vagrant-libvirt` plugin, a KVM host with `qemu-kvm` and `cyrus-sasl-md5`, and a user in the `libvirt` group.

Each node is AlmaLinux 10 with nested KVM, set up by `dev/libvirt-bootstrap.sh` (with this checkout's gstfsd), with:

- a SASL user for TCP (`wvc`, password `wvc-test`) and your `~/.ssh/id_ed25519.pub` for root;
- TLS logins (SASL) with certificates from a throwaway CA that `vagrant up` makes in `.vagrant/tls`; the TLS run takes its client certificate from there through `HOME`;
- an empty second disk (`/dev/vdb`) for the LVM tests, a 1 GiB iSCSI LUN on 127.0.0.1 for the iSCSI test and an NFS export (`/srv/wvc-nfs`) to 127.0.0.1 for the NFS pool test.

Migration runs between the two. On a host that also runs Docker, let the VMs' network (the bridge of `virsh net-info vagrant-libvirt`, `virbr1` here) through Docker's forward rules:

```bash
sudo iptables -I DOCKER-USER -i virbr1 -j ACCEPT
sudo iptables -I DOCKER-USER -o virbr1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

Start the nodes and run the suite over TCP (compute1) and SSH (compute2):

```bash
vagrant up --provider=libvirt
C1=$(vagrant ssh compute1 -c "hostname -I" | awk '{print $1}') C2=$(vagrant ssh compute2 -c "hostname -I" | awk '{print $1}')
for h in $C1 $C2; do ssh-keygen -R $h; ssh -o StrictHostKeyChecking=accept-new root@$h true; done   # new VMs, new host keys
export TEST_LIBVIRT_HOST=$C1 TEST_LIBVIRT_TYPE=1 TEST_LIBVIRT_LOGIN=wvc TEST_LIBVIRT_PASSWORD=wvc-test
export TEST_LIBVIRT_SSH_HOST=$C2 TEST_LIBVIRT_SSH_LOGIN=root TEST_LIBVIRT_MIGRATE_ADDRESS=$C2 TEST_LIBVIRT_LVM_DEVICE=/dev/vdb TEST_LIBVIRT_ISCSI_TARGET=iqn.2026-10.test.wvc:lun TEST_LIBVIRT_NFS_EXPORT=/srv/wvc-nfs
python manage.py test
```

Over TLS, compute1 again:

```bash
HOME=$PWD/.vagrant/tls TEST_LIBVIRT_TYPE=3 TEST_LIBVIRT_SSH_HOST= python manage.py test
```

Over the local socket: a socket compute is the panel's own libvirt, so the committed HEAD runs inside compute1:

```bash
git archive HEAD | vagrant ssh compute1 -c "sudo sh -c 'rm -rf /root/wvc && mkdir /root/wvc && tar -x -C /root/wvc'"
vagrant ssh compute1 -c "sudo -i sh -ec 'dnf -y install python3-devel openldap-devel cyrus-sasl-devel gcc; cd /root/wvc; python3 -m venv --system-site-packages venv; venv/bin/pip install -r dev/requirements.txt; mkdir data; venv/bin/python conf/secret_generator.py > data/secret_key; TEST_LIBVIRT_HOST=localhost TEST_LIBVIRT_TYPE=4 TEST_LIBVIRT_LOGIN=wvc TEST_LIBVIRT_PASSWORD=wvc-test TEST_LIBVIRT_LVM_DEVICE=/dev/vdb TEST_LIBVIRT_ISCSI_TARGET=iqn.2026-10.test.wvc:lun TEST_LIBVIRT_NFS_EXPORT=/srv/wvc-nfs venv/bin/python manage.py test'"
```

Remove the nodes:

```bash
vagrant destroy -f
```
