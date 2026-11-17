from django.utils.translation import gettext_noop
from lxml import etree

from storages.forms import inside
from vrtManager.util import InUse

from .models import Backup, BackupTargetPool


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
        if volume.startswith(backup.prefix + "-"):
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
