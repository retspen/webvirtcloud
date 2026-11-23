# Users, Roles and Permissions

WebVirtCloud combines three kinds of access rights:

- **Superuser** (`is_superuser`): full administration — computes, storage pools, networks, interfaces, nwfilters, secrets, app settings, users, and every VM.
- **Global permissions** (Django permissions, set per user or group in the admin pages):
  - `instances.view_instances` — **read-only auditor role**: sees every VM in lists and detail pages, but cannot change them and cannot open their consoles.
  - `instances.clone_instances` — may clone VMs (see the table for which ones).
  - `instances.snapshot_instances` — may create, revert and delete snapshots of VMs they may change.
  - `instances.backup_instances` — may back up the VMs they may change (see the table).
  - `instances.passwordless_console` — the console page fills in the VNC password automatically, and the `.vv` file holds it (ticked by default on the Users page's new-user form; a user made otherwise, such as from LDAP, does not get it).
  - `accounts.change_password` — may change their own password (a local one; LDAP users change theirs in LDAP).
- **Per-VM ownership** (an owner entry for a user on a VM, managed by a superuser on the VM's page) with three flags: `is_change`, `is_delete`, `is_vnc`. An owner without flags may see, start and stop the VM and open its console.

| Action on a VM | Superuser | Owner | Owner flag / permission needed | `view_instances` only |
|---|---|---|---|---|
| Create a VM; the VM report (Excel) | ✅ | ❌ | — | ❌ |
| See the VM (list, detail) | ✅ | ✅ | — | ✅ |
| Start, shut down, power cycle, force off | ✅ | ✅ | — | ❌ |
| Open the console (noVNC or, when it is on, the serial console; `.vv` file for virt-viewer, VDI URL) | ✅ | ✅ | — | ❌ |
| Resize CPU/memory/disk, set root password, add SSH key, change title/description | ✅ | ✅ | `is_change` | ❌ |
| Change console settings (type, VNC password, keymap) | ✅ | ✅ | `is_change` and `is_vnc`; the listen address, and removing the password of a console that listens beyond localhost, are a superuser's; nobody's on a template | ❌ |
| Snapshots | ✅ | ✅ | `is_change` and `instances.snapshot_instances` | ❌ |
| Clone | ✅ | ✅ | `is_change` and `instances.clone_instances` (templates: viewing the template is enough) | templates only, with `instances.clone_instances` |
| Delete the VM, with its disk files when chosen | ✅ | ✅ | `is_delete` | ❌ |
| Disks and media (add, attach, edit, detach, delete volumes; CD-ROM/ISO) | ✅ | ❌ | — | ❌ |
| Network interfaces, host devices (PCI/USB), boot options, vCPU hotplug, autostart, guest agent, video, RNG, TPM, crash and hang action, disk I/O limits, suspend/resume, migrate, disk moves, protection, raw XML, owners | ✅ | ❌ | — | ❌ |
| Set tags (owners and `view_instances` see them) | ✅ | ❌ | — | ❌ |
| Backups: back up (within the backup quota), restore over the VM or as a new VM (within the VM quota), into and from targets open to VM owners | ✅ | ✅ | `is_change` and `instances.backup_instances` | ❌ |
| Delete a backup one took by hand (not a schedule's) on a target open to VM owners | ✅ | ✅ | `instances.backup_instances` (ownership not needed) | ❌ |
| Verify a backup; restore one of its disks as a new volume | ✅ | ❌ | — | ❌ |
| Backup targets and schedules | ✅ | ❌ | — | ❌ |

Notes:

- Only superusers choose disk names and MAC addresses when cloning; for other users the server derives them.
- `is_staff` gives no access to VMs and does not reveal console settings or VNC passwords by itself.
- A VM an administrator paused stays paused for its owners: their power actions on it are refused.
- A protected VM (a superuser's setting on its Settings tab) is neither deleted nor restored over, by anyone, until the protection is turned off.
- The VM list's bulk start, shut down, force off and snapshot follow the rows above for each chosen VM (templates take no bulk snapshot); bulk tagging is a superuser's.
- The Jobs page shows a user the jobs they started; superusers see every job.
- Finding VMs by IP or MAC address searches a user's own VMs; superusers and `view_instances` users search every host.
- An API token acts with its user's rights: the API allows what the pages allow, but its backup endpoints are a superuser's.
- A template VM is changed (resize, root password, SSH keys, title and description, snapshots) only by superusers and by staff owners with `is_change`, deleted only by superusers and staff owners with `is_delete`, and backed up only by superusers; other owners keep view, console and power (power on and power cycle of a template are refused with a warning). Cloning a template needs only view access and `instances.clone_instances`.
- On VM pages, users without ownership or `view_instances` get **404** (the VM's existence is not revealed), and users who can see a VM but lack the right for an action get **403**. Superuser-only pages answer **403** to everyone else; the console page answers **403** both for a missing VM and for a VM the user may not open.
