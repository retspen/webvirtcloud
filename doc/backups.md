# Backups

The panel backs itself up every day at 03:15 (cron in Docker; otherwise `webvirt-backup.timer`, within 10 minutes after and at the next boot if the server was off) into a new directory under `/srv/webvirtcloud/backups`, in Docker the `webvirtcloud-backups` volume, and keeps the newest 7. A backup holds:

- `db.sqlite3`: a consistent copy taken while the panel runs, checked with `PRAGMA integrity_check`; with PostgreSQL it is left out, so back up that database yourself
- `secret_key`, `node_id` and `local_settings.py`
- `ssh/`: the SSH keys of the panel's user, which the SSH computes accept
- `pki/`: the TLS client certificates of the panel's user, which the TLS computes accept
- `commit`, outside Docker

The database holds compute passwords and keys: the directories are readable only by the panel's user. They are on the same host as the panel; the [off-site copy](#off-site-copy) keeps them on another server too. A failed backup is reported in `docker logs` or by `systemctl status webvirt-backup` and deletes no older backup.

Take one now:

```bash
docker compose exec -u www-data webvirtcloud venv/bin/python3 manage.py backup   # Docker
systemctl start webvirt-backup && journalctl -u webvirt-backup -n 3                          # otherwise
```

To restore one, follow [Restore and rollback](upgrading.md#restore-and-rollback) with `b` set to its directory. In Docker, copy it out of the volume first (`docker compose cp webvirtcloud:/srv/webvirtcloud/backups/webvirtcloud-backup-YYYYMMDD-HHMMSS ..`) and leave out the `git checkout` and `build` lines: the backup has no commit. To move the panel to a new machine, see [Moving to a new machine](upgrading.md#moving-to-a-new-machine).

## Off-site copy

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
b=$(find /root/offsite-restore -type d -name 'webvirtcloud-backup-*' -printf '%T@ %p\n' | sort -n | tail -n 1 | cut -d' ' -f2-)
```

and follow [Moving to a new machine](upgrading.md#moving-to-a-new-machine) with that `b` (leave out its `b=` line).

## VM backups

Superusers back a VM up from its **Backups** tab into a backup target: a `dir` or `netfs` storage pool made on each host that sees it, added on **Backups → Backup targets** (another host's pool is accepted only when it is the same directory). A running VM keeps running: its disks are copied from one instant, with its file systems frozen for it when the guest agent answers; a shut-off VM's disks are copied as they are. A backup holds the disks, the VM's definition, its UEFI variables, its TPM state and a manifest; a VM with a TPM is backed up shut off. It is restored as a new VM, with its network disconnected unless asked, on a host that has the target's pool; the new VM gets the backed-up VM's TPM state. A backup is also restored over its own shut-off VM (its disks copied as new volumes it is switched to, its UEFI variables and TPM state back to the backup's, the old volumes kept until deleted), or one of its disks as a new volume. After the panel's database is lost, add the target again and use **Read backups from target**.

Users with the **Can back up instances** permission back up the VMs they may change into targets opened to VM owners on the target's page, restore those backups over the VM (the disks it ran from are then deleted) or as a new VM on the VM's host, within their quota, and delete the backups they took; those count in their backup quota (GiB, with the user's quota).

VMs with a TPM of their own settings (encryption, a state path), host devices, shared host directories, or encrypted or non-file disks are not backed up; CD-ROMs are left out.

**Backups → Schedules** backs VMs up every day: chosen VMs, every VM of a compute or every VM with a chosen tag (not templates), into a target, at a time in the panel's time zone (`TZ`), keeping the newest backups of each VM up to a number, and optionally the newest backup of each of the last N weeks and of the last N months. The job worker starts each VM's backup within 6 hours of the time, one copy at a time per target, and waits for a host in maintenance; a VM not started in that window waits for the next day. Older backups of a schedule are deleted; backups taken by hand are not. With "A full backup every N backups" above 1, a schedule's backups of a running VM with qcow2 disks between two full ones copy only what changed since the previous one; each is restored like a full one, and a chain of them is deleted once all of it is beyond the number kept. A migration, a restore over the VM or a shut-off VM's backup makes the next one full. Each target is checked once a day: a backup whose files are gone is marked missing.

**Verify** (a ready backup's Restore menu, superusers) reads the backup's files whole from the target, with those of the backups it builds on: each must be there at its size and format, an incremental disk on its base's file, and every file with the SHA-256 it had when written or, for a disk, at its first verification (recorded then; a disk changed since is reported). What is wrong marks the backup **Damaged**; the job can be cancelled.

The target must be:

- on storage apart from the VMs' disks: a target on the same storage is lost with it;
- writable by QEMU;
- with NFS on SELinux hosts, allowed: `setsebool -P virt_use_nfs 1`.

An NFS target, on each host:

```bash
virsh -c qemu:///system pool-define-as vmbackups netfs --source-host nfs.example.com --source-path /export/vmbackups --target /var/lib/libvirt/vmbackups
virsh -c qemu:///system pool-build vmbackups && virsh -c qemu:///system pool-start vmbackups && virsh -c qemu:///system pool-autostart vmbackups
```

The panel does not copy VM backups off site: the target's storage does.
