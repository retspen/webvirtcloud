# WebVirtCloud architecture

WebVirtCloud is a web panel for libvirt hosts. libvirt is the source of truth: the panel reads a host's VMs, pools, networks and devices from libvirt when a page needs them, and its database holds what libvirt does not (users, permissions, quotas, compute connection details, jobs, the audit log, settings) and, per VM, the compute, name and UUID that permissions hang on. VMs keep running when the panel is stopped. Changes made with `virsh` or `virt-manager` reach those VM rows the next time a VM list page is loaded; the API's list of a compute's VMs reconciles them with libvirt first, its list of all VMs reads the rows as they are.

## Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.10–3.14, Django 5.2 LTS |
| Database | SQLite (WAL) by default, PostgreSQL optional |
| libvirt | `libvirt-python`, `lxml` for the XML |
| API | Django REST Framework, `drf-nested-routers`, `drf-spectacular` (OpenAPI 3.0), API tokens (`django-rest-knox`) |
| Frontend | Django templates, Bootstrap 5, Bootstrap Icons, vendored jQuery, Chart.js, noVNC, xterm.js |
| Security | `django-otp` (TOTP), `django-axes` (lockout), optional `django-auth-ldap`; CSP `script-src 'self'` |
| Serving | nginx in front of gunicorn (gthread workers) and WhiteNoise |
| Processes | systemd units on hosts, supervisord in the Docker image |

## Processes

```
browser ── nginx :80 (:443 with your TLS)
             ├── /            → gunicorn 127.0.0.1:8000 (Django)
             ├── /static/     → staticfiles/
             ├── /novncd/     → novncd 127.0.0.1:6080 (VNC console, websockify)
             └── /socket.io/  → socketiod 127.0.0.1:6081 (serial console)

worker (manage.py run_worker)  long operations, one per installation
backup (manage.py backup)      daily, from webvirt-backup.timer or cron in Docker

Django, worker, novncd, socketiod ── libvirt (TCP, SSH, TLS or local socket) ── compute hosts
panel ── gstfsd on each compute, at the compute's hostname, port 16510 (HMAC-signed requests; loopback only when the panel runs on the compute)
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
| `admin` | users, groups and their permissions pages |
| `appsettings` | settings stored in the database, themes, `manage.py backup` |
| `computes` | compute hosts (`Compute`: hostname, type, login, password, gstfsd key, migration address), host overview and capacity |
| `instances` | VMs (`Instance`: compute, name, UUID), flavors, removed-VM records (`InstanceTombstone`), the VM pages and their jobs |
| `storages`, `networks`, `interfaces`, `nwfilters`, `virtsecrets` | the host's pools and volumes, networks, interfaces, network filters and secrets, read from libvirt |
| `nodedevs` | the host's PCI and USB devices and which VM has them |
| `console` | VNC and serial console pages, signed console tokens, `novncd`, `socketiod`, SSH tunnels to SSH computes |
| `datasource` | cloud-init metadata (OpenStack format), a VM found by its client address |
| `logs` | the audit log (`Logs`) and its page |
| `operations` | jobs: `Operation`, `Claim`, `WorkerLease`, the worker and the Jobs pages |

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

Long operations (create, clone, migrate and delete VMs, move disks, clone volumes, snapshots, ISO uploads) are `Operation` rows. The worker claims queued jobs and runs them on a thread pool; an ISO upload runs in the web request and is only tracked.

- **Claims:** a job holds claims on what it changes (VM, volume, pool, name, quota); a conflicting request is refused at once.
- **Recovery:** a job whose worker died is never run again. The new worker reads what happened from libvirt and ends it as succeeded, failed or uncertain; an uncertain job keeps its claims until a superuser resolves it.
- **Hosts:** one host's jobs take at most half the worker's slots, with one progress read and one control task per host, so a host that does not answer cannot stop the others.
- **Pages:** the job panel on resource pages, the Jobs pages and `/api/v1/operations/` follow them.

## API

`/api/v1/` (session from the login form or an API token):

- `computes/`, and per compute `instances/`, `instances/create/<arch>/<machine>/`, `networks/`, `interfaces/`, `storages/` (with `volumes/`), `archs/`
- `instances/`, `flavor/`, `migrate/`, `operations/`
- schema at `/api/schema/`, Swagger at `/swagger/`, ReDoc at `/redoc/`

Create, migrate and delete answer 202 with the job.
