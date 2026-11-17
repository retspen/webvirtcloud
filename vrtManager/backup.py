"""VM backups: the target pools and what a VM's backup holds (app vmbackups)."""

import libvirt
from django.utils.translation import gettext_noop
from lxml import etree

from vrtManager.util import OperationError

# pools that keep their volumes as files in one directory
TARGET_TYPES = ("dir", "netfs")


def target_pool(conn, name, uuid=None):
    """The active dir or netfs pool name of conn's host; with uuid, only the
    pool a target registered, not another made since under its name."""
    try:
        pool = conn.get_storage(name)
        usable = (
            pool.isActive()
            and etree.fromstring(pool.XMLDesc(0)).get("type") in TARGET_TYPES
            and uuid in (None, pool.UUIDString())
        )
    except libvirt.libvirtError as err:
        if err.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_POOL:
            raise
        usable = False
    if not usable:
        raise OperationError(
            gettext_noop(
                "Storage pool %(pool)s is not an active directory or NFS pool of this host, "
                "or not the one the backup target registered"
            ),
            pool=name,
        )
    return pool


def pool_space(pool):
    """{name, size, free, used_percent} of a pool, as the storage pages show
    it; refreshed first, as files may have changed outside libvirt."""
    pool.refresh(0)
    _state, size, used, free = pool.info()
    return {"name": pool.name(), "size": size, "free": free, "used_percent": used * 100 / size if size else 0}
