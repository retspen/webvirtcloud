# Adding a Compute Node

A compute node is a KVM host the panel manages over libvirt. Before you add one, make sure the compute's VNC ports (`5900`–`65535`) accept connections **only** from the panel's IP, never from public networks.

## 1. Install KVM and libvirt

The bootstrap script handles Ubuntu, Debian, CentOS, Fedora, Rocky Linux and AlmaLinux 10, openEuler 24.03 LTS, openSUSE and SLES:

```bash
curl -fsSL https://raw.githubusercontent.com/retspen/webvirtcloud/master/dev/libvirt-bootstrap.sh | sudo sh
# or, from a cloned repository: sudo sh ./dev/libvirt-bootstrap.sh
```

- **RHEL** needs EPEL from its release RPM, so do not run the script there: install the `qemu-kvm`, `libvirt` and `python3-libguestfs` (for [gstfsd](#3-install-gstfsd)) packages yourself and enable the sockets of the daemons the panel talks to, `virt{qemu,network,storage,nodedev,nwfilter,secret,interface}d.socket` (for TCP also `virtproxyd-tcp.socket` and SASL, set up as `dev/libvirt-bootstrap.sh` does on EL10).
- **UEFI, Secure Boot and TPM:** the new VM form offers UEFI, UEFI Secure Boot (with Microsoft's keys, for Windows 11) and a TPM 2.0 only when the host's libvirt finds the UEFI firmware and swtpm: install `ovmf swtpm-tools` (Debian / Ubuntu) or `edk2-ovmf swtpm swtpm-tools` (RHEL family, openEuler) if they are missing.

## 2. Let the panel connect

Set up the connection type you will choose on the Computes page: SSH, TCP or TLS. A panel installed on the compute itself (installer or manual installation) can use the local socket, which needs nothing here.

### SSH

Give the user the panel runs as an SSH key and copy it to the compute node. **Use only the block for your installation type:** a key set up with the host commands is not seen by the panel in Docker. `ssh-copy-id` asks for the compute node's root password once. `accept-new` accepts a new host's key on first connect and refuses a changed one.

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

### TCP

The bootstrap script makes libvirt ask for a SASL login. Create it on the compute node and enter it, with its password, on the Computes page (`saslpasswd2` is in `sasl2-bin` on Debian / Ubuntu and in `cyrus-sasl` on the RHEL family):

```bash
sudo saslpasswd2 -a libvirt <login>   # asks for its password
```

### TLS

**On the panel host:** put the CA certificate and the panel's client certificate and key in the panel user's `~/.pki/libvirt/` as `cacert.pem`, `clientcert.pem` and `clientkey.pem`, readable only by that user: in the home of `www-data` (`nginx` on RHEL / openSUSE) with the installer or a manual installation; in Docker `/var/www/.pki/libvirt/` (the `webvirtcloud-pki` volume), owned by `www-data`.

**On the compute node:** install the same CA certificate and a server certificate whose subjectAltName is the address the panel uses, then let libvirt listen for TLS:

```bash
sudo install -D -m 644 cacert.pem /etc/pki/CA/cacert.pem
sudo install -D -m 644 servercert.pem /etc/pki/libvirt/servercert.pem
sudo install -D -m 600 serverkey.pem /etc/pki/libvirt/private/serverkey.pem
# RHEL family 10 (the modular daemons: the bootstrap enabled virtproxyd-tcp.socket):
sudo systemctl stop virtproxyd.service; sudo systemctl enable --now virtproxyd-tls.socket
# the other systems (libvirtd):
sudo systemctl stop libvirtd.service; sudo systemctl enable --now libvirtd-tls.socket && sudo systemctl start libvirtd.service
```

## 3. Install gstfsd

gstfsd sets the root password and SSH key of a shut-off VM. The bootstrap script already installed it and made its key; read the key for step 4 with `sudo cat /etc/default/webvirt-gstfsd`. Without the script, or to update gstfsd:

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

gstfsd does only what the panel signs with this key. It listens on 127.0.0.1:16510 only, which serves a panel on the compute itself that adds it as `localhost` or `127.0.0.1`.

**A panel on another machine or in a container** (the Docker setup, also on the compute) reaches it at the compute's address. Its traffic is not encrypted, and a password hash crosses it: allow TCP 16510 only from the panel's IP, on a network you trust. Then let it in:

```bash
sudo sed -i '/^GSTFSD_BIND_HOST=/d; /^GSTFSD_ALLOW_REMOTE=/d' /etc/default/webvirt-gstfsd
printf 'GSTFSD_BIND_HOST=0.0.0.0\nGSTFSD_ALLOW_REMOTE=1\n' | sudo tee -a /etc/default/webvirt-gstfsd > /dev/null
sudo systemctl restart webvirt-gstfsd
```

A running VM gets its password and keys through its QEMU guest agent instead, without gstfsd. On RHEL-family guests, SELinux lets the agent add SSH keys only after `sudo setsebool -P virt_qemu_ga_manage_ssh on` inside the guest.

## 4. Add the compute

Add it on the panel's Computes page, with the `GSTFSD_KEY` value from step 3 as its gstfsd key.

If libvirt warns `Host SMBIOS information is not available`, install `dmidecode` (`apt-get`, `dnf` or `zypper install -y dmidecode`) and restart `libvirtd` (`virtqemud` on the RHEL family 10).

## Migration

- **Shared storage:** define it as a storage pool on every host. A VM migrates when its disk, backing and ISO files and block devices are volumes of the destination's pools.
- **Without shared storage:** after choosing the destination, the **Disks** list shows each disk and the destination pools that can take a copy (directory, filesystem and NFS pools; a pool with a file of the same name refuses it); a disk on storage both hosts share can stay there. Plain raw or qcow2 disks without a backing file are copied, through the destination's migration port range (49152-49215 by default). **Delete the source files of copied disks** removes them after the migration, unless another VM or volume uses them.
- **Shut-off VMs:** a shut-off VM moves offline, with its NVRAM file (UEFI). When its disks are copied or it has a TPM, it is started paused for the migration instead (its CPUs never run) and shut off on the destination.
- **Hosts that differ:** the Computes page's box above the hosts names a host that lacks an active network, a network filter or a secret the VMs of another host use, or has a filter of that name with other rules: the migration check refuses moving those VMs there.
- **Address:** a migrating VM goes to the destination's address on the Computes page; for a dedicated migration network, set the compute's **Migration address** on its edit page.
- **Bandwidth:** **Settings → Migrations** gives libvirt a limit in MiB/s, so a migration leaves room for the VMs' own traffic. It applies to the memory transfer until the final switchover and to each copied disk on its own (two disks may take twice it); a shut-off VM's UEFI variables file is not limited. 0 leaves libvirt's default, no limit unless one was set on the host.
- **Encryption:** QEMU sends a VM's memory and copied disks in the clear. With **Encrypt migrations (TLS)** ticked on both hosts' edit pages (Advanced), it sends them over TLS. Each host then needs:
  - QEMU's certificates from one CA in `/etc/pki/qemu`: `ca-cert.pem`, `server-cert.pem`, `server-key.pem`, `client-cert.pem` and `client-key.pem`
  - readable by QEMU: owner `root`, group the one QEMU runs as (`qemu` on the RHEL family and openSUSE, `kvm` on Debian and Ubuntu), keys `0640`
  - a server certificate naming the host's migration address (or the address the panel reaches it at) as it is written there, a name or an IP

  A host without them refuses the migration before anything moves: `Unable to access credentials /etc/pki/qemu/ca-cert.pem`.
