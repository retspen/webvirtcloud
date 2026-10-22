from contextlib import contextmanager
import logging
from datetime import timedelta

from accounts.models import UserInstance
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from computes.models import Compute
from instances.models import Instance, InstanceTombstone
from operations import claims
from operations.models import Claim

logger = logging.getLogger(__name__)


@contextmanager
def libvirt_compute_lock(compute, *, shared=False):
    """The compute for the block: exclusive keeps out every VM operation and
    reconcile on it; shared lets sibling VMs and reconciles go on. Busy if it is taken."""
    compute_pk = getattr(compute, "pk", getattr(compute, "id", None))
    if not compute_pk:
        yield
        return
    with claims.hold({claims.compute_key(compute_pk): Claim.SHARED if shared else Claim.EXCLUSIVE}):
        yield


@contextmanager
def user_quota_lock(user):
    """One user's quota check and the change it allows run one at a time."""
    with claims.hold({claims.quota_key(user.pk): Claim.EXCLUSIVE}):
        yield


@contextmanager
def libvirt_instance_lock(instance):
    """One VM for the block, sharing its compute with sibling VMs."""
    compute = instance.compute
    with claims.hold({
        claims.compute_key(getattr(compute, "pk", getattr(compute, "id", None))): Claim.SHARED,
        claims.instance_key(instance.uuid): Claim.EXCLUSIVE,
    }):
        yield


def _move_ownership(source, target):
    """Give target the owners and template flag of source; a user's rights are merged."""
    for ui in UserInstance.objects.filter(instance=source):
        existing = UserInstance.objects.filter(instance=target, user=ui.user).first()
        if existing is None:
            ui.instance = target
            ui.save(update_fields=["instance"])
            continue
        for flag in ("is_change", "is_delete", "is_vnc"):
            if getattr(ui, flag):
                setattr(existing, flag, True)
        existing.save()
    if source.is_template and not target.is_template:
        target.is_template = True
        target.save(update_fields=["is_template"])


def forget(inst):
    """Remove an instance whose VM its compute no longer lists, or whose
    compute is deleted. Its ownership goes to the same UUID on another
    compute (an out-of-band move) or is kept in a tombstone in case the VM
    comes back."""
    elsewhere = Instance.objects.filter(uuid=inst.uuid).exclude(compute_id=inst.compute_id).first()
    if elsewhere:
        _move_ownership(inst, elsewhere)
    else:
        _bury(inst)
    inst.delete()


def _bury(inst):
    owners = [
        {"user": ui.user_id, "is_change": ui.is_change, "is_delete": ui.is_delete, "is_vnc": ui.is_vnc}
        for ui in UserInstance.objects.filter(instance=inst)
    ]
    if owners or inst.is_template:
        InstanceTombstone.objects.create(uuid=inst.uuid, name=inst.name, is_template=inst.is_template, owners=owners)
        logger.info("Instance %s (%s) disappeared; ownership kept", inst.name, inst.uuid)


def _restore(inst):
    tombstone = InstanceTombstone.objects.filter(uuid=inst.uuid).order_by("-removed").first()
    if tombstone is None:
        return
    users = set(get_user_model().objects.filter(id__in=[o["user"] for o in tombstone.owners]).values_list("id", flat=True))
    for owner in tombstone.owners:
        if owner["user"] in users:
            UserInstance.objects.create(
                instance=inst,
                user_id=owner["user"],
                is_change=owner["is_change"],
                is_delete=owner["is_delete"],
                is_vnc=owner["is_vnc"],
            )
    if tombstone.is_template:
        inst.is_template = True
        inst.save(update_fields=["is_template"])
    InstanceTombstone.objects.filter(uuid=inst.uuid).delete()
    logger.info("Instance %s (%s) is back; ownership restored", inst.name, inst.uuid)


def refresh_instance_database(compute):
    """
    Synchronizes the WebVirtCloud database with libvirt domain state.
    Libvirt is the single source of truth:
      - VMs removed in virt-manager/virsh are deleted from the database; their
        ownership is moved to the same UUID on another compute or kept in a
        tombstone for INSTANCE_OWNERSHIP_RETENTION_DAYS.
      - VMs created in virt-manager/virsh are added to the database.
      - VMs renamed in virt-manager/virsh have their name updated without losing
        UserInstance permission relationships (matched by UUID).
      - If libvirt is unreachable (connection/network error), the database is left
        untouched to avoid false deletions.
    """
    compute_pk = getattr(compute, "pk", getattr(compute, "id", None))
    if not compute_pk:
        return

    try:
        # The compute shared: VM operations and jobs on it go on; changes of
        # its VM set (create, clone, delete, migration, define) hold it
        # exclusive and stay out until the end. One reconcile of a compute at
        # a time: two would read libvirt at different times and could commit
        # in reverse order, an older listing undoing a newer one.
        with claims.hold({claims.compute_key(compute_pk): Claim.SHARED,
                          claims.reconcile_key(compute_pk): Claim.EXCLUSIVE}):
            # libvirt is asked before the transaction: a silent host can keep a
            # call waiting for 30 s, and on SQLite an open transaction makes every
            # other write of the app fail meanwhile.
            if hasattr(compute, "status") and compute.status is False:
                return

            try:
                domains = compute.proxy.wvm.listAllDomains()
            except Exception as e:
                logger.warning(
                    "Failed to retrieve domains from compute %s (%s): %s",
                    getattr(compute, "name", compute),
                    getattr(compute, "hostname", ""),
                    e,
                )
                return

            # Map libvirt UUIDs to current domain names
            host_domains = {}
            for d in domains:
                try:
                    host_domains[d.UUIDString()] = d.name()
                except Exception as e:
                    logger.warning(
                        "Error reading domain metadata from compute %s: %s",
                        getattr(compute, "name", compute),
                        e,
                    )
                    return

            with transaction.atomic():
                # the compute may have been deleted while libvirt was asked
                comp_locked = Compute.objects.select_for_update().filter(pk=compute_pk).first()
                if not comp_locked:
                    return

                db_instances = list(Instance.objects.filter(compute=compute).select_for_update())
                db_uuids = set(inst.uuid for inst in db_instances)

                # 1. Update name for any VM whose name changed out-of-band in virsh/virt-manager
                for inst in db_instances:
                    if inst.uuid in host_domains:
                        new_name = host_domains[inst.uuid]
                        if inst.name != new_name:
                            inst.name = new_name
                            inst.save(update_fields=["name"])

                # 2. Instances gone from this compute
                for inst in db_instances:
                    if inst.uuid not in host_domains:
                        forget(inst)

                # 3. Instances created out-of-band. A UUID that also exists on another
                #    compute is a copy and gets no owners; otherwise a tombstone's
                #    ownership is restored.
                retention = getattr(settings, "INSTANCE_OWNERSHIP_RETENTION_DAYS", 30)
                InstanceTombstone.objects.filter(removed__lt=timezone.now() - timedelta(days=retention)).delete()
                for uuid, name in host_domains.items():
                    if uuid not in db_uuids:
                        inst, created = Instance.objects.get_or_create(
                            compute=compute,
                            uuid=uuid,
                            defaults={"name": name},
                        )
                        if created and not Instance.objects.filter(uuid=uuid).exclude(compute=compute).exists():
                            _restore(inst)
    except claims.Busy:
        logger.debug("Compute %s is busy; not synchronized now", compute_pk)
        return
