# WebVirtCloud architecture

WebVirtCloud is a web panel for libvirt hosts. libvirt is the source of truth; VMs keep running when the panel is stopped.

- **libvirt holds** the VMs, pools, networks and devices; the panel reads them when a page needs them.
- **The panel's database holds** what libvirt does not: users, permissions, quotas, compute connection details, jobs, the audit log, settings and, per VM, the compute, name and UUID that permissions hang on.
- **Changes made with `virsh` or `virt-manager`** (VMs added, removed or renamed) reach the database the next time a VM list is read: the VM list page and both API VM lists read first the hosts whose VMs the user may see.

## Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.10–3.14, Django 5.2 LTS |
| Database | SQLite (WAL) by default, PostgreSQL optional |
| libvirt | `libvirt-python`, `lxml` for the XML |
| API | Django REST Framework, `drf-nested-routers`, `drf-spectacular` (OpenAPI 3.0), API tokens (`django-rest-knox`) |
| Frontend | Django templates, Bootstrap 5, Bootstrap Icons, vendored jQuery, Chart.js, noVNC, xterm.js |
| Security | `django-otp` (TOTP), `django-axes` (lockout), optional `django-auth-ldap`; CSP `script-src 'self'` |
| Serving | nginx in front of gunicorn (gthread workers); nginx serves the static files |
| Processes | systemd units on hosts, supervisord in the Docker image |

Every page is sent with `X-Frame-Options: DENY` and `Content-Security-Policy: script-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`: the panel runs only scripts it serves itself, cannot be shown in a frame, and its forms post only to its own origin.

## Processes

```
browser ── nginx :80 (:443 with your TLS)
             ├── /            → gunicorn 127.0.0.1:8000 (Django)
             ├── /static/     → staticfiles/
             ├── /novncd/     → novncd 127.0.0.1:6080 (VNC console, websockify)
             └── /socket.io/  → socketiod 127.0.0.1:6081 (serial console, off by default)

worker (manage.py run_worker)  long operations, one per installation
backup (manage.py backup)      daily, from webvirt-backup.timer or cron in Docker

Django, worker, novncd, socketiod ── libvirt (TCP, SSH, TLS or local socket) ── compute hosts
panel ── gstfsd on a compute, optional (root password and SSH key of a shut-off VM), port 16510 (HMAC-signed requests; loopback only unless set up for a remote panel)
```

| Unit (systemd) | supervisord program (Docker) | Runs |
|---|---|---|
| `webvirt-cloud` | `gunicorn` | gunicorn |
| `webvirt-novncd` | `novncd` | `console/novncd` |
| `webvirt-socketiod` | `socketiod` | `console/socketiod` |
| `webvirt-worker` | `worker` | `manage.py run_worker` |
| `webvirt-backup.timer` | `cron` (`/etc/cron.d/webvirtcloud-backup`) | `manage.py backup` |
| `webvirt-gstfsd` (on computes) | | `conf/daemon/gstfsd` |

## Apps

| App | What it holds |
|---|---|
| `accounts` | users' VM permissions (`UserInstance`), quotas (`UserAttributes`), SSH keys, API tokens, OTP, login |
| `admin` | users, groups and their permissions pages, the Tags and Logs pages |
| `appsettings` | settings stored in the database, themes, `manage.py backup` |
| `computes` | compute hosts (`Compute`: hostname, type, login, password, gstfsd key, migration address, maintenance), tags (`Tag`) of VMs and hosts, host overview and capacity, Bulk Migrate and Balance |
| `instances` | VMs (`Instance`: compute, name, UUID), flavors, removed-VM records (`InstanceTombstone`), the VM pages and their jobs |
| `storages`, `networks`, `interfaces`, `nwfilters`, `virtsecrets` | the host's pools and volumes, networks, interfaces, network filters and secrets, read from libvirt |
| `nodedevs` | the host's PCI and USB devices and which VM has them |
| `console` | VNC and serial console pages, signed console tokens, `novncd`, `socketiod`, SSH tunnels to SSH computes |
| `datasource` | cloud-init metadata (OpenStack format), a VM found by the reverse-DNS name of its client address |
| `logs` | the audit log (`Logs`), its helpers and the VM page's Logs tab |
| `operations` | jobs: `Operation`, `Claim`, `WorkerLease`, the worker and the Jobs pages |
| `vmbackups` | VM backups: targets (a storage pool per compute), backups and their files, schedules (`BackupPolicy`), their jobs and pages |

## vrtManager

The libvirt layer: the connections and the host objects the apps work on (the apps use `libvirt` itself only for its errors and constants).

| Module | Does |
|---|---|
| `connection.py` | one shared connection per host, transport and login, opened again when it closes (not more often than a pause allows after a failed open); a host gets at most two web requests at a time per process, so one that does not answer holds two threads and refuses the rest |
| `instance.py` | a VM: power, disks, NICs, CPU, memory, snapshots, clone, live clone (push backup), migration, stats |
| `create.py` | the XML of a new VM |
| `hostdetails.py` | host CPU, memory and capabilities |
| `storage.py`, `network.py`, `interface.py`, `nwfilters.py`, `virtsecrets.py`, `nodedevs.py` | the host objects of the apps with the same names |
| `util.py` | `OperationError` (its text translated when shown, English in logs), XML helpers |

## Jobs

Long operations (create, clone, migrate and delete VMs, bulk power, move disks, clone and download volumes, snapshots, VM backups, ISO uploads) are `Operation` rows. The worker claims queued jobs and runs them on a thread pool; an ISO upload runs in the web request and is only tracked.

- **Claims:** a job holds claims on what it changes (VM, volume, pool, name, quota); a conflicting request is refused at once.
- **Recovery:** a job whose worker died is never run again. The new worker reads what happened from libvirt and ends it as succeeded, failed, cancelled or uncertain; an uncertain job keeps its claims until a superuser resolves it.
- **Hosts:** one host's jobs take at most half the worker's slots, with one progress read and one control task per host, so a host that does not answer cannot stop the others.
- **Pages:** the job panel on resource pages, the Jobs pages and `/api/v1/operations/` follow them.

## API

`/api/v1/`, used as [REST API](api.md) describes:

- `computes/`, and per compute `instances/`, `instances/create/<arch>/<machine>/`, `networks/`, `interfaces/`, `storages/` (with `volumes/`), `archs/`
- `instances/`, `flavor/`, `migrate/`, `operations/`, `backups/`
