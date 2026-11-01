import os
import random
import re
import string

from accounts.models import UserInstance, UserAttributes
from appsettings.settings import app_settings
from computes.models import Compute
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError
from logs.audit import reason, write
from operations.models import Operation
from vrtManager.connection import wvmConnect
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.util import OperationError

from .models import Instance


def can_open_console(user, instance):
    """
    The single rule for console access (noVNC page, novncd, the virt-viewer
    .vv file and the VDI URL): an active superuser or an active owner of the
    VM. The global view_instances permission is read-only and does not grant
    an interactive console.
    """
    if not user.is_active:
        return False
    if user.is_superuser:
        return True
    return UserInstance.objects.filter(instance=instance, user=user).exists()


def get_clone_free_names(size=10):
    prefix = app_settings.CLONE_INSTANCE_DEFAULT_PREFIX
    free_names = []
    existing_names = [i.name for i in Instance.objects.filter(name__startswith=prefix)]
    index = 1
    while len(free_names) < size:
        new_name = prefix + str(index)
        if new_name not in existing_names:
            free_names.append(new_name)
        index += 1
    return free_names


def paths_used_on_other_computes(compute, own):
    """The paths in own that the VMs and volumes of the panel's other computes
    use (paths_in_use): shared storage holds a file at the same path on every
    host that mounts it, as migration needs. OperationError naming a compute
    that cannot be read: it might use them."""
    used = set()
    host = wvmConnect(compute.hostname, compute.login, compute.password, compute.type).host_uuid()
    for other in Compute.objects.exclude(pk=compute.pk):
        try:
            conn = wvmConnect(other.hostname, other.login, other.password, other.type)
            if host and conn.host_uuid() == host:
                continue  # the VM's own host under another record: its VM is the one going
            used |= conn.paths_in_use(own=own)
        except libvirtError as err:
            raise OperationError(_("The disk files cannot be checked on %(host)s: %(err)s") % {
                "host": other.name, "err": err.get_error_message()}) from err
    return used & set(own)


def disk_gib(disks):
    """The size of the disks in whole GiB each, as the quota counts them."""
    return sum(int(disk["size"] or 0) >> 30 for disk in disks)


# check_user_quota could not read every VM of the user: an increase is refused
QUOTA_UNVERIFIED = "unverified"


def check_user_quota(user, instance, cpu, memory, disk_size):
    """
    Which quota the user would exceed by adding these amounts (instances,
    vCPUs, memory MiB, disk GiB) to their VMs, or "". A quota of -1 has no
    limit; 0 allows none. QUOTA_UNVERIFIED if a
    VM that counts cannot be read (its host is down, the VM is gone): the
    usage is unknown, so an increase is refused.
    """
    ua, attributes_created = UserAttributes.objects.get_or_create(user=user)
    msg = ""

    if user.is_superuser:
        return msg
    # adding nothing (a shrink) cannot exceed a quota
    if instance <= 0 and cpu <= 0 and memory <= 0 and disk_size <= 0:
        return msg

    quota_debug = app_settings.QUOTA_DEBUG == "True"

    user_instances = UserInstance.objects.filter(user=user, instance__is_template=False).select_related(
        "instance__compute"
    )
    # a clone counts from its job's admission until its VM is recorded
    clones = [
        op.intent["quota"] for op in Operation.objects.filter(
            user=user, kind="instance.clone", state__in=Operation.ACTIVE + (Operation.UNCERTAIN,))
        if "quota" in op.intent and not Instance.objects.filter(uuid=op.intent["uuid"]).exists()
    ]
    instance += user_instances.count() + len(clones)
    if ua.max_instances >= 0 and instance > ua.max_instances:
        msg = "instance"
        if quota_debug:
            msg += f" ({instance} > {ua.max_instances})"
        return msg
    if ua.max_cpus < 0 and ua.max_memory < 0 and ua.max_disk_size < 0:
        return msg

    for clone in clones:
        cpu += clone["cpus"]
        memory += clone["memory"]
        disk_size += clone["disk"]
    computes = {}  # status is cached per object: check each host once
    for usr_inst in user_instances:
        vm = usr_inst.instance
        compute = computes.setdefault(vm.compute_id, vm.compute)
        if compute.status is not True:
            return QUOTA_UNVERIFIED
        try:
            conn = wvmInstance(
                compute.hostname,
                compute.login,
                compute.password,
                compute.type,
                vm.name,
                uuid=vm.uuid,
            )
            # a running VM counts what it has, or what it gets at its next start if that is more
            with conn.cached_reads():
                cpu += max(conn.get_vcpu(), conn.get_vcpu(config=True))
                memory += max(conn.get_memory(), conn.get_memory(config=True))
                disk_size += max(disk_gib(conn.get_disk_devices()), disk_gib(conn.get_disk_devices(config=True)))
        except libvirtError:
            return QUOTA_UNVERIFIED

    if ua.max_cpus >= 0 and cpu > ua.max_cpus:
        msg = "cpu"
        if quota_debug:
            msg += f" ({cpu} > {ua.max_cpus})"
    if ua.max_memory >= 0 and memory > ua.max_memory:
        msg = "memory"
        if quota_debug:
            msg += f" ({memory} > {ua.max_memory})"
    if ua.max_disk_size >= 0 and disk_size > ua.max_disk_size:
        msg = "disk"
        if quota_debug:
            msg += f" ({disk_size} > {ua.max_disk_size})"
    return msg


def get_new_disk_dev(media, disks, bus):
    existing_disk_devs = []
    existing_media_devs = []
    if bus == "virtio":
        dev_base = "vd"
    elif bus == "ide":
        dev_base = "hd"
    elif bus == "fdc":
        dev_base = "fd"
    else:
        dev_base = "sd"

    if disks:
        existing_disk_devs = [disk["dev"] for disk in disks]

    # cd-rom bus could be virtio/sata, because of that we should check it also
    if media:
        existing_media_devs = [m["dev"] for m in media]

    for al in string.ascii_lowercase:
        dev = dev_base + al
        if dev not in existing_disk_devs and dev not in existing_media_devs:
            return dev
    raise Exception(_("None available device name"))


def get_network_tuple(network_source_str):
    network_source_pack = network_source_str.split(":", 1)
    if len(network_source_pack) > 1:
        return network_source_pack[1], network_source_pack[0]
    else:
        return network_source_pack[0], "net"


def migrate_instance(
    new_compute,
    instance,
    user,
    live=False,
    unsafe=False,
    offline=False,
    autoconverge=False,
    compress=False,
    delete_source=False,
    disk_pools=None,
):
    """Migrates instance to new_compute and logs the outcome (the mode
    used, or the error), then each later step that failed in a row of its
    own. disk_pools: {target: pool} of the disks copied into pools of
    new_compute (moveto's pools); their source files go with delete_source
    unless another VM or volume uses them, and are named in the log
    otherwise. Returns the mode."""
    source, target = instance.compute, migration_target(new_compute)

    def log(action, error=None):
        message = f"VM {instance.name}: {action}" + (f": {reason(error, user)}" if error is not None else "")
        write(user.username, source.name, instance.name, message, error is None, uuid=instance.uuid)

    conn_migrate = None
    try:
        conn_migrate = wvmInstances(
            new_compute.hostname,
            new_compute.login,
            new_compute.password,
            new_compute.type,
        )

        autostart = instance.proxy.get_autostart()
        nvram = instance.proxy.get_nvram()
        mode, copied = conn_migrate.moveto(
            instance.proxy,
            instance.name,
            live,
            unsafe,
            offline,
            autoconverge,
            compress,
            uri=new_compute.migration_uri,
            pools=disk_pools,
        )
    except Exception as error:
        log(f"migrate to {target}", error)
        raise
    finally:
        if conn_migrate is not None:
            conn_migrate.close()

    # The VM runs on new_compute now: what follows must not stop it
    # from being recorded there.
    log(f"migrate ({mode}) to {target}")
    if autostart:
        conn_new = None
        try:
            conn_new = wvmInstance(
                new_compute.hostname,
                new_compute.login,
                new_compute.password,
                new_compute.type,
                instance.name,
                uuid=instance.uuid,
            )
            conn_new.set_autostart(1)
        except (libvirtError, OSError) as error:
            log(f"restore autostart on {target}", error)
        finally:
            if conn_new is not None:
                conn_new.close()

    in_use = set()
    if copied and delete_source:
        try:
            in_use = instance.proxy.paths_in_use()
        except libvirtError as error:
            log("check the source copies before deleting them", error)
            delete_source = False
    for path in copied:
        if not delete_source or path in in_use:
            log(f"keep the source copy {path}" + (": another VM or volume uses it" if path in in_use else ""))
            continue
        try:
            instance.proxy.get_volume_by_path(path).delete(0)
        except libvirtError as error:
            log(f"delete the source copy {path}", error)
        else:
            log(f"delete the source copy {path}")

    # libvirt keeps the NVRAM file on the source; a VM created there
    # later with the same name would start with these variables.
    if nvram:
        conn_new = None
        try:
            conn_new = wvmInstances(
                new_compute.hostname, new_compute.login, new_compute.password, new_compute.type
            )
            instance.proxy.remove_nvram(nvram, conn_new)
        except Exception as error:  # the migration stands and is recorded
            log(f"remove NVRAM file {nvram} on the source", error)
        finally:
            if conn_new is not None:
                conn_new.close()

    try:
        record_migration(instance, new_compute)
    except Exception as error:
        log(f"record the move to {target}", error)
        raise
    return mode


def record_migration(instance, new_compute):
    """Moves instance to new_compute in the database. A record the list of
    new_compute made for it meanwhile takes its owners and template mark."""
    with transaction.atomic():
        target_inst = Instance.objects.filter(compute=new_compute, uuid=instance.uuid).first()
        if target_inst and target_inst.id != instance.id:
            for ui in UserInstance.objects.filter(instance=instance):
                existing_ui = UserInstance.objects.filter(instance=target_inst, user=ui.user).first()
                if not existing_ui:
                    ui.instance = target_inst
                    ui.save()
                else:
                    updated = False
                    if ui.is_change and not existing_ui.is_change:
                        existing_ui.is_change = True
                        updated = True
                    if ui.is_delete and not existing_ui.is_delete:
                        existing_ui.is_delete = True
                        updated = True
                    if ui.is_vnc and not existing_ui.is_vnc:
                        existing_ui.is_vnc = True
                        updated = True
                    if updated:
                        existing_ui.save()
                    ui.delete()
            if instance.is_template and not target_inst.is_template:
                target_inst.is_template = True
                target_inst.save(update_fields=["is_template"])
            instance.delete()
            instance.id = target_inst.id
            instance.compute = new_compute
        else:
            instance.compute = new_compute
            instance.save()


def vm_states(user, computes):
    """{compute pk: {"ok": True, "vms": {uuid: [name, state]}}, or {"ok": False}
    for a host that cannot be read}: what the VM lists poll, read from libvirt;
    for a user who does not see hosts only their own VMs (a VM is its host and
    UUID: one UUID may be defined on two hosts)."""
    show_hosts = user.is_superuser or user.has_perm("instances.view_instances")
    own = None if show_hosts else set(
        Instance.objects.filter(userinstance__user=user).values_list("compute_id", "uuid"))
    result = {}
    for compute in computes:
        try:
            vms = compute.proxy.get_domain_states() if compute.status is True else None
        except libvirtError:
            vms = None
        result[str(compute.pk)] = {"ok": False} if vms is None else {
            "ok": True, "vms": {u: s for u, s in vms.items() if own is None or (compute.pk, u) in own}}
    return result


def migration_target(compute):
    """The destination for the log: its host name, and the migration address
    when one is set and differs (else the migration goes to the host name)."""
    if compute.migration_address not in ("", compute.hostname):
        return _("%(hostname)s via %(address)s") % {"hostname": compute.hostname, "address": compute.migration_address}
    return compute.hostname


def refr(compute):
    from computes.utils import refresh_instance_database

    refresh_instance_database(compute)


def dhcpd_conf():
    """Optional dhcpd.conf in the application directory; clone names and MAC
    addresses are taken from its host entries when it exists."""
    return os.path.join(str(settings.BASE_DIR), "dhcpd.conf")


def get_dhcp_mac_address(vname):
    dhcp_file = dhcpd_conf()
    mac = ""
    if os.path.isfile(dhcp_file):
        with open(dhcp_file, "r") as f:
            name_found = False
            for line in f:
                if "host %s." % vname in line:
                    name_found = True
                if name_found and "hardware ethernet" in line:
                    mac = line.split(" ")[-1].strip().strip(";")
                    break
    return mac


MAC_ADDRESS_RE = re.compile(r"^([0-9A-F]{2})(:?[0-9A-F]{2}){5}$", re.IGNORECASE)


def nic_macs(mac, networks):
    """The MAC addresses given for a new VM's NICs, in network order. NICs
    without one get theirs from libvirt."""
    macs = [m.strip() for m in mac.split(",")] if mac else []
    if not all(MAC_ADDRESS_RE.fullmatch(m) for m in macs):
        raise ValueError(_("Invalid MAC address"))
    if len(macs) > len(networks.split(",")):
        raise ValueError(_("More MAC addresses than networks"))
    return macs


def get_random_mac_address():
    mac = settings.MAC_OUI + ":%02x:%02x:%02x" % (
        random.randint(0x00, 0xFF),
        random.randint(0x00, 0xFF),
        random.randint(0x00, 0xFF),
    )
    return mac


def get_clone_disk_name(disk, prefix, clone_name):
    """A volume name for the clone's copy of disk: the clone's name in place of
    the source's (prefix), else before the disk's device and name, so two disks
    of one clone do not get the same name."""
    if not disk["image"]:
        return None
    if disk["image"].startswith(prefix):
        suffix = disk["image"][len(prefix) :]
        image = f"{clone_name}{suffix}"
    elif "." in disk["image"] and len(disk["image"].rsplit(".", 1)[1]) <= 7:
        name, suffix = disk["image"].rsplit(".", 1)
        image = f"{clone_name}-{disk['dev']}-{name}.{suffix}"
    else:
        image = f"{clone_name}-{disk['dev']}-{disk['image']}"
    # Derived names go into volume XML and paths: keep them to a safe charset.
    image = re.sub(r"[^A-Za-z0-9_.+-]+", "-", image).lstrip("_.+-")
    return image or None


def can_manage_console(user, instance):
    """
    Who may see and change a VM's console settings, including its VNC
    password: an active superuser, or an active owner with both is_change and
    is_vnc; on a template only a staff owner (as get_instance(perm_type="change")).
    is_staff and the global view_instances permission alone do not count.
    """
    if not user.is_active:
        return False
    if user.is_superuser:
        return True
    if instance.is_template and not user.is_staff:
        return False
    return UserInstance.objects.filter(
        instance=instance, user=user, is_change=True, is_vnc=True
    ).exists()
