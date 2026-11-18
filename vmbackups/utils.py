from django.db.models import Q
from django.utils.translation import gettext, gettext_noop
from libvirt import libvirtError
from lxml import etree

from storages.forms import inside
from vrtManager.backup import wvmBackup
from vrtManager.util import InUse

from .models import Backup, BackupPolicy, BackupTarget, BackupTargetPool


def inside_vm_pool(conn, pool):
    """The name of another pool of the host whose directory holds the target
    pool's: its backups would share that storage's failures."""
    path = etree.fromstring(pool.XMLDesc(0)).findtext("target/path").rstrip("/")
    for name, (_pool, directory) in conn.file_pools().items():
        if name != pool.name() and inside(path, directory):
            return name
    return None


def refuse_backup_volume(compute, pool, volume):
    """A volume of a backup is deleted with its backup, on the Backups pages."""
    for backup in Backup.objects.filter(target__pools__compute=compute, target__pools__pool=pool):
        if backup.owns(volume):
            raise InUse(
                gettext_noop("Volume %(volume)s belongs to a backup of %(vm)s; delete the backup on the Backups page"),
                volume=volume,
                vm=backup.vm_name,
            )


def refuse_target_pool(compute, pool):
    row = BackupTargetPool.objects.filter(compute=compute, pool=pool).select_related("target").first()
    if row:
        raise InUse(
            gettext_noop("Storage pool %(pool)s is backup target %(target)s; remove it from the target first"),
            pool=pool,
            target=row.target.name,
        )


def pending_deletes():
    """The UUIDs of the backups a deletion job was asked for and has not
    finished: shown as being deleted before the job marks them."""
    from operations.models import Operation

    ops = Operation.objects.filter(kind="backup.delete", state__in=Operation.ACTIVE).values_list("params", flat=True)
    return {params["backup"] for params in ops}


def vm_tab(instance, user):
    """The VM page's Backups tab: the VM's backups, the targets of its host,
    and why it cannot be backed up, if it cannot. A VM owner sees only
    targets open to VM owners, and no schedule."""
    owner = not user.is_superuser
    targets = BackupTarget.objects.filter(pools__compute=instance.compute)
    rows = instance.backups.select_related("target", "operation")
    if owner:
        targets, rows = targets.filter(owners=True), rows.filter(target__owners=True)
    targets = list(targets.order_by("name"))
    problem = None
    if not targets:
        problem = (gettext("No backup target open to VM owners has a storage pool on this VM's host.") if owner
                   else gettext("No backup target has a storage pool on this VM's host."))
    else:
        c = instance.compute
        try:
            wvmBackup(c.hostname, c.login, c.password, c.type, instance.name, uuid=instance.uuid).backup_plan()
        except libvirtError as err:
            problem = str(err)
    schedules = [] if owner else BackupPolicy.objects.filter(
        Q(instances=instance) | Q(compute=instance.compute_id)).distinct().order_by("name")
    return {"rows": rows, "targets": targets, "problem": problem, "schedules": schedules,
            "pending_deletes": pending_deletes()}
