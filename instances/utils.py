import os
import random
import re
import string
import threading
from collections import namedtuple

from accounts.models import UserInstance, UserAttributes
from appsettings.settings import app_settings
from computes.models import Compute
from computes.utils import lock_ownership, move_ownership
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from libvirt import libvirtError
from logs.audit import reason, write
from operations.models import Operation
from vrtManager.connection import other_hosts, wvmConnect
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.util import ConnectionFailed, message, vol_dev_type

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


@other_hosts()
def paths_used_on_other_computes(compute, own):
    """The paths in own that the VMs and volumes of the panel's other computes
    use (paths_in_use): shared storage holds a file at the same path on every
    host that mounts it, as migration needs. ConnectionFailed naming a compute
    that cannot be read, which might use them: users who do not see hosts
    learn only that a host cannot be reached."""
    used = set()
    host = wvmConnect(compute.hostname, compute.login, compute.password, compute.type).host_uuid()
    for other in Compute.objects.exclude(pk=compute.pk):
        try:
            conn = wvmConnect(other.hostname, other.login, other.password, other.type)
            if host and conn.host_uuid() == host:
                continue  # the VM's own host under another record: its VM is the one going
            used |= conn.paths_in_use(own=own)
        except libvirtError as err:
            raise ConnectionFailed(gettext_noop("The disk files cannot be checked on %(host)s: %(err)s"),
                                   host=other.name, err=err) from err
    return used & set(own)


USED_CHECK_WAIT = 60  # seconds a disk move or a migration waits for the computes to tell whether its old file is used


def used_anywhere(path, skip=None):
    """Whether a VM or volume of any compute uses path (paths_in_use), as
    shared storage holds it for every host that mounts it; a compute that
    cannot be read might, and so might one that does not answer within
    USED_CHECK_WAIT: libvirt has no call timeout, and a stuck host would
    hold the job for as long as it is stuck. skip: a compute not asked."""
    computes = list(Compute.objects.exclude(pk=skip))
    answer = []

    def check():
        for c in computes:
            try:
                if path in wvmConnect(c.hostname, c.login, c.password, c.type).paths_in_use():
                    answer.append(True)
                    return
            except libvirtError:
                answer.append(True)
                return
        answer.append(False)

    thread = threading.Thread(target=check, daemon=True)
    thread.start()
    thread.join(USED_CHECK_WAIT)
    return answer[0] if answer else True


def disk_gib(disks):
    """The size of the disks in whole GiB each, as the quota counts them."""
    return sum(int(disk["size"] or 0) >> 30 for disk in disks)


# check_user_quota could not read every VM of the user: an increase is refused
QUOTA_UNVERIFIED = "unverified"
QUOTA_UNVERIFIED_TEXT = gettext_noop(
    "The quota cannot be checked: a host of your virtual machines cannot be reached, or the size of one of "
    "their disks cannot be read. Nothing was changed.")

# The quota a change would exceed: instance, cpu, memory or disk, the total it
# would make and the limit
QuotaExceeded = namedtuple("QuotaExceeded", "kind total limit")
QUOTA_REACHED = {
    "instance": gettext_noop("The quota of virtual machines is reached"),
    "cpu": gettext_noop("The vCPU quota is reached"),
    "memory": gettext_noop("The memory quota is reached"),
    "disk": gettext_noop("The disk quota is reached"),
}


def quota_message(exceeded):
    """The quota check's result as messages, with the numbers when QUOTA_DEBUG is on."""
    reached = message(QUOTA_REACHED[exceeded.kind])
    if app_settings.QUOTA_DEBUG != "True":
        return [reached]
    return [message(gettext_noop("%(quota)s (%(total)s > %(limit)s)"),
                    quota=[reached], total=exceeded.total, limit=exceeded.limit)]


@other_hosts()
def check_user_quota(user, instance, cpu, memory, disk_size):
    """
    The quota the user would exceed by adding these amounts (instances,
    vCPUs, memory MiB, disk GiB) to their VMs, a QuotaExceeded, or "". A quota of -1 has no
    limit; 0 allows none. QUOTA_UNVERIFIED if a
    VM that counts cannot be read (its host is down, the VM is gone, a disk's
    size is unknown): the usage is unknown, so an increase is refused.
    """
    ua, attributes_created = UserAttributes.objects.get_or_create(user=user)
    msg = ""

    if user.is_superuser:
        return msg
    # adding nothing (a shrink) cannot exceed a quota
    if instance <= 0 and cpu <= 0 and memory <= 0 and disk_size <= 0:
        return msg

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
        return QuotaExceeded("instance", instance, ua.max_instances)
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
                disks = conn.get_disk_devices(), conn.get_disk_devices(config=True)
            if ua.max_disk_size >= 0 and any(disk["size"] is None for devices in disks for disk in devices):
                return QUOTA_UNVERIFIED  # not 0 GiB
            disk_size += max(map(disk_gib, disks))
        except libvirtError:
            return QUOTA_UNVERIFIED

    if ua.max_cpus >= 0 and cpu > ua.max_cpus:
        msg = QuotaExceeded("cpu", cpu, ua.max_cpus)
    if ua.max_memory >= 0 and memory > ua.max_memory:
        msg = QuotaExceeded("memory", memory, ua.max_memory)
    if ua.max_disk_size >= 0 and disk_size > ua.max_disk_size:
        msg = QuotaExceeded("disk", disk_size, ua.max_disk_size)
    return msg


def get_new_disk_dev(media, disks, bus):
    existing_disk_devs = []
    existing_media_devs = []
    dev_base = vol_dev_type(bus) or "sd"

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
    ip=None,
    on_moved=None,
    on_copy=None,
):
    """Migrates instance to new_compute and logs the outcome (the mode
    used, or the error), then each later step that failed in a row of its
    own; on_moved is called once the outcome's row is written. disk_pools:
    {target: pool} of the disks copied into pools of new_compute (moveto's
    pools), on_copy as moveto's; their source files go with delete_source unless a VM or volume
    of any compute may use them (used_anywhere), and are named in the log
    otherwise. Returns the mode."""
    source, target = instance.compute, migration_target(new_compute)

    def log(action, error=None):
        message = f"VM {instance.name}: {action}" + (f": {reason(error, user)}" if error is not None else "")
        write(user.username, source.name, instance.name, message, error is None, ip, instance.uuid)

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
            on_copy=on_copy,
        )
    except Exception as error:
        log(f"migrate to {target}", error)
        raise

    # The VM runs on new_compute now: what follows must not stop it
    # from being recorded there.
    log(f"migrate ({mode}) to {target}")
    if on_moved is not None:  # its row is written: a later step that raises does not undo it
        on_moved()
    if autostart:
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

    for path, copy in copied:
        # shared storage: a VM or volume of any compute may use it; the destination's
        # VM uses the copy, another file when it has the same path there
        used = delete_source and used_anywhere(path, skip=new_compute.pk if copy == path else None)
        if not delete_source or used:
            log(f"keep the source copy {path}" + (": a VM or volume of a compute may use it" if used else ""))
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
        try:
            conn_new = wvmInstances(
                new_compute.hostname, new_compute.login, new_compute.password, new_compute.type
            )
            instance.proxy.remove_nvram(nvram, conn_new)
        except Exception as error:  # the migration stands and is recorded
            log(f"remove NVRAM file {nvram} on the source", error)

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
        # owners are moved here: not while a sync of a third compute moves them too
        lock_ownership()
        target_inst = Instance.objects.filter(compute=new_compute, uuid=instance.uuid).first()
        if target_inst and target_inst.id != instance.id:
            move_ownership(instance, target_inst)
            instance.delete()
            instance.id = target_inst.id
            instance.compute = new_compute
        else:
            instance.compute = new_compute
            instance.save()


def read_list_rows(instances):
    """Each VM's info and title for a VM list, read once a host
    (get_domain_rows), not three calls a VM; a VM whose host or whose
    domain cannot be read has no info: the list shows it unknown."""
    rows, shown = {}, {}
    for inst in instances:
        shown.setdefault(inst.compute_id, set()).add(inst.uuid)
    for compute in {inst.compute_id: inst.compute for inst in instances}.values():
        try:
            rows[compute.pk] = compute.proxy.get_domain_rows(shown[compute.pk]) if compute.status is True else {}
        except libvirtError:
            rows[compute.pk] = {}
    for inst in instances:
        inst.info, inst.title = rows[inst.compute_id].get(inst.uuid, (None, ""))


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
    is_vnc. No one on a template: it is cloned, not run.
    is_staff and the global view_instances permission alone do not count.
    """
    if not user.is_active or instance.is_template:
        return False
    if user.is_superuser:
        return True
    return UserInstance.objects.filter(
        instance=instance, user=user, is_change=True, is_vnc=True
    ).exists()
