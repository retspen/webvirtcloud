# WebVirtCloud - Codebase Overview and Architecture Documentation

This document describes the architectural design, core components, data flow, and module interactions of the **WebVirtCloud** project.

---

## 1. Overview & Purpose

**WebVirtCloud** is an open-source virtualization management platform designed to manage QEMU/KVM-based hypervisors and virtual machines (instances) through a modern web UI and REST API.

The platform provides:
- **For Administrators**: Centralized multi-host hypervisor management, storage pools and volumes, virtual networks, compute nodes, and user quotas.
- **For End Users**: Self-service virtual machine control (start, stop, reboot, console access, snapshot management, and live resource monitoring) based on delegated permissions.

---

## 2. Technology Stack

| Layer | Technology / Library | Description |
|---|---|---|
| **Runtime** | Python >= 3.11 (tested up to 3.12) | Modern Python runtime environment |
| **Web Framework** | Django 4.2 LTS | Core web framework, ORM, and MVC application foundation |
| **API** | Django REST Framework (DRF) + `drf-spectacular` | RESTful API endpoints with OpenAPI 3.0 / Swagger & ReDoc documentation |
| **Virtualization API** | `libvirt-python` + `lxml` | Libvirt API bindings and dynamic domain/storage/network XML generation |
| **Console / VNC** | WebSockify + noVNC | In-browser HTML5 VNC/SPICE console access via WebSocket |
| **Frontend** | Django Templates, Bootstrap 5, Bootstrap Icons, jQuery | Server-rendered responsive and dynamic user interface |
| **Identity & Security** | Django Auth, `django-otp` (2FA/TOTP), `django-auth-ldap` | Role-based authorization, two-factor authentication, and optional LDAP/Active Directory support |
| **Web / WSGI Server** | Nginx + Gunicorn + WhiteNoise | Static file delivery and reverse proxy architecture |
| **Process Manager** | Supervisor / Runit / Systemd | Background service management for Gunicorn, novncd, and socketiod |

---

## 3. System Architecture & Core Layers

```
                               +-----------------------------+
                               |     Web Browser / Client    |
                               +--------------+--------------+
                                              |
                        HTTP / HTTPS (Port 80/443)   WebSockets (Port 6080)
                                              |              |
                                              v              v
+------------------------------------------------------------------------------------+
| Nginx Reverse Proxy                                                                |
|   ├── /static/  --> Static Assets (WhiteNoise / Nginx)                             |
|   ├── /         --> Gunicorn (Django WSGI Application)                             |
|   └── :6080     --> WebSockify (novncd background service)                         |
+-------------------------------------+----------------------------------------------+
                                      |
                                      v
+------------------------------------------------------------------------------------+
| Django Application Layer (WebVirtCloud)                                            |
|                                                                                    |
|  [accounts]      Users, Roles, Quotas, SSH Keys, 2FA (TOTP), LDAP                  |
|  [computes]      Hypervisor (Compute Node) connection profiles                     |
|  [instances]     Virtual machine models, lifecycle, live migration, flavors        |
|  [storages]      Storage pools and volumes (dir, lvm, rbd/ceph, nfs, etc.)         |
|  [networks]      Virtual networks (NAT, isolated, bridge, routed)                  |
|  [interfaces]    Physical and bridged host network interfaces                      |
|  [nwfilters]     Network filtering and firewall rules (anti-spoofing)              |
|  [virtsecrets]   Libvirt secrets management (Ceph auth, etc.)                      |
|  [datasource]    Cloud-init metadata and userdata HTTP endpoints                   |
|  [logs]          User and system audit trail logging                               |
|  [api/v1]        DRF Nested Routers exposing full REST API                         |
+-------------------------------------+----------------------------------------------+
                                      |
                                      v
+------------------------------------------------------------------------------------+
| vrtManager Layer (Libvirt Abstraction Engine)                                      |
|   ├── connection.py  --> TCP, SSH, TLS, or local socket libvirt connection pooling  |
|   ├── instance.py    --> XML domain generation, CPU/RAM/Disk/Snapshots/Metrics     |
|   ├── storage.py     --> Storage pool & volume XML management                      |
|   ├── network.py     --> Network XML configuration & IP allocation                 |
|   └── hostdetails.py --> Node info, memory, and CPU utilization metrics            |
+-------------------------------------+----------------------------------------------+
                                      |
                       Libvirt Protocol (TCP/SSH/TLS/Socket)
                                      |
                                      v
+------------------------------------------------------------------------------------+
| KVM / QEMU Hypervisor Hosts                                                        |
|   ├── libvirtd / virtqemud                                                         |
|   ├── QEMU Guest Domains (VMs) + QEMU Guest Agent                                  |
|   └── Storage & Network Infrastructure (ZFS, LVM, Ceph RBD, Linux Bridge, OVS)     |
+------------------------------------------------------------------------------------+
```

---

## 4. Module & Directory Structure Analysis

### 4.1. `vrtManager/` (Core Libvirt Abstraction Engine)
The most critical Python package in the project. Instead of persisting hypervisor and VM runtime states statically in a database, WebVirtCloud queries libvirt live in real time.
- **`connection.py`**: Manages the libvirt connection pool (`connection_manager`) supporting multiple protocols (`CONN_TCP`, `CONN_SSH`, `CONN_TLS`, `CONN_SOCKET`). Uses a reentrant `ReadWriteLock` for thread-safe concurrent access.
- **`instance.py`**: Encapsulates VM lifecycle operations via the `wvmInstance` class (start, shutdown, force off, suspend, resume, dynamic CPU/RAM allocation, disk hotplug/unplug, XML modification, snapshots, and real-time vCPU, network I/O, and disk I/O metrics).
- **`create.py`**: Dynamically compiles XML definitions to provision new virtual machines.
- **`storage.py` & `network.py`**: Handles storage pools (directory, LVM, iSCSI, Ceph RBD) and virtual network configurations.
- **`hostdetails.py`**: Queries host capabilities, hardware architecture, total/available memory, and CPU utilization.

### 4.2. `computes/` (Hypervisor Management)
- Manages hypervisor host records (`hostname`, `login`, `password`, `type`).
- Provides lazy connection retrieval via `cached_property` using `connection_manager`.
- Exposes host architectures (`archs`), processor topology, and memory state via REST API endpoints.

### 4.3. `instances/` (Virtual Machine Management)
- **`Instance` Model**: Stores the relational link between a VM and its `compute` node, unique `uuid`, and `name`. Runtime state (power state, memory, vCPUs, disks, network interfaces) is dynamically resolved through the `vrtManager.instance.wvmInstance` proxy.
- **`Flavor` Model**: Predefined sizing templates (vCPU, RAM, disk) similar to AWS EC2 or OpenStack flavors.
- **`MigrateInstance`**: Implements VM live migration, offline migration, compressed transfer, or unsafe tunneling to another compute host.
- **`views.py`**: Provides VM provisioning wizards, configuration editors, cloning, snapshot management, and power controls.

### 4.4. `accounts/` (Users, Permissions & Quotas)
- Extends standard Django `User` model with granular virtualization delegation:
  - **`UserInstance`**: Delegates granular permissions for a specific VM to a user (read, modify `is_change`, delete `is_delete`, console `is_vnc`).
  - **`UserAttributes`**: Sets per-user resource quotas (maximum instances, maximum vCPUs, maximum RAM, and maximum storage capacity).
  - **`UserSSHKey`**: Stores public SSH keys that can be injected automatically into new VMs via Cloud-Init.
  - Supports Two-Factor Authentication (TOTP / QR code) and optional enterprise LDAP/Active Directory synchronization.

### 4.5. `console/` (Remote Console Access)
- **`novncd`**: Python-based WebSockify daemon bridging browser-based noVNC clients to the hypervisor's VNC/SPICE TCP ports via WebSockets.
- **`sshtunnels.py`**: If the hypervisor is remote and VNC ports are not publicly exposed, establishes an on-demand encrypted SSH tunnel to forward console traffic safely.

### 4.6. `datasource/` (Cloud-Init Support)
- Implements a Cloud-Init compatible HTTP metadata and userdata service.
- When a VM boots for the first time, it contacts `http://<webvirtcloud>/datasource/`.
- Resolves the VM identity based on the client IP address and delivers the owner's SSH public keys as a formatted `user-data` payload, enabling automated passwordless SSH provisioning.

### 4.7. `storages/`, `networks/`, `interfaces/`, `nwfilters/`, `virtsecrets/`
- **`storages`**: Storage pool management (dir, LVM, NFS, iSCSI, Ceph RBD), ISO image uploads, volume cloning, and disk resizing.
- **`networks`**: Virtual network creation (NAT, Routed, Bridge, Isolated), DHCP address pools, and static IP/MAC bindings.
- **`interfaces`**: Host physical network interfaces, bonding, and Linux bridge management.
- **`nwfilters`**: Anti-spoofing firewall and packet filtering rules at the hypervisor level.
- **`virtsecrets`**: Libvirt secrets management (e.g., Ceph authentication keys).

### 4.8. `logs/`, `appsettings/`, and `admin/`
- **`logs`**: Comprehensive audit trail recording user and system actions (power on, shutdown, disk attachment, user modification).
- **`appsettings`**: Dynamic configuration stored in the database (custom titles, permissions, UI options) exposed globally via Django context processors.
- **`admin`**: Administrative control panel for user, group, and system-level management.

---

## 5. REST API Architecture (`/api/v1/`)

Built on Django REST Framework with `drf-nested-routers`, providing a structured hierarchical API:

- `/api/v1/computes/` : List and manage hypervisors
  - `/api/v1/computes/{id}/instances/` : VMs running on a specific hypervisor
  - `/api/v1/computes/{id}/instances/create/{arch}/{machine}/` : VM creation endpoint
  - `/api/v1/computes/{id}/networks/` : Virtual networks on the hypervisor
  - `/api/v1/computes/{id}/interfaces/` : Host network interfaces
  - `/api/v1/computes/{id}/storages/` : Storage pools
    - `/api/v1/computes/{id}/storages/{id}/volumes/` : Storage volumes (disks)
  - `/api/v1/computes/{id}/archs/` : Supported architectures and machine types
- `/api/v1/instances/` : Global virtual machine list
- `/api/v1/flavor/` : Sizing templates (flavors)
- `/api/v1/migrate/` : VM migration operations
- `/swagger/` & `/redoc/` : Live OpenAPI 3.0 documentation (powered by `drf-spectacular`)

---

## 6. Deployment & Service Lifecycle

1. **Gunicorn**: WSGI application server running `webvirtcloud.wsgi:application` (binds to a Unix socket or port 8000).
2. **novncd**: Background WebSockify daemon translating VNC/SPICE TCP ports to WebSockets on port 6080.
3. **Nginx**: Front-facing reverse proxy handling ports 80/443, serving static assets directly, proxying dynamic web requests to Gunicorn, and routing WebSocket console traffic to `novncd`.
4. **Supervisor / Runit / Systemd**: Process supervision managing Gunicorn and novncd daemon lifecycles with automatic restarts.

---

## 7. Architecture Highlights

WebVirtCloud leverages a hybrid pattern: it combines the relational strengths of the **Django ORM** for persistent entities (users, compute host credentials, quotas, and permission delegations) with direct, real-time **libvirt C API bindings** for dynamic virtualization state (VM statuses, resource allocation, storage metrics, and live hardware statistics). This design ensures that the web console always reflects the true hypervisor state without risk of database desynchronization.
