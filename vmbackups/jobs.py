"""Jobs of the vmbackups app (operations framework)."""

import datetime
import hashlib
import itertools
import json
import os
import re
import time
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.http import Http404
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_noop as _
from lxml import etree
from libvirt import VIR_DOMAIN_PAUSED, VIR_DOMAIN_RUNNING, VIR_DOMAIN_SHUTOFF, VIR_ERR_NO_DOMAIN, VIR_ERR_NO_STORAGE_VOL, libvirtError

from accounts.models import UserAttributes
from appsettings.settings import app_settings
from computes.models import Compute
from instances.jobs import MOVED, PAUSED_FROZEN, THAW_FAILED, _instance, _log, _snapshot_free_space, record_vm, vm_claims
from instances.utils import QUOTA_UNVERIFIED, paths_used_on_other_computes, QUOTA_UNVERIFIED_TEXT, check_user_quota, get_random_mac_address, quota_message
from instances.models import Instance
from operations import claims
from operations.jobs import Cancelled, Kind, Outcome, Plan, register, register_periodic
from operations.models import Claim, Operation
from operations.utils import safe_text, say
from vrtManager import util
from vrtManager.backup import (backup_file_names, check_restore_host, check_target_space, get_file, manifest_names, put_file,
                               remove_files, restore_definition, restore_over_definition, target_pool, volume_exists,
                               wvmBackup)
from vrtManager.connection import NVRAM_DIR, wvmConnect
from vrtManager.instance import PERSISTENT_XML, wvmInstance
from vrtManager.storage import wvmStorage
from vrtManager.instance import LIVE_CLONE_MIN_LIBVIRT

from .models import Backup, BackupFile, BackupPolicy, BackupTarget

MANIFEST_FORMAT = 1
NVRAM_READS = 3  # a running VM's NVRAM read after its backup, until it is the one read before
NVRAM_WAIT = 5  # seconds between those reads
CHECK_SETTLE = datetime.timedelta(minutes=10)  # an NFS client lists another's new files within minutes
PROGRESS_EVERY = 2  # seconds between reads of a push backup's progress


def _superuser(user):
    if user is None or not user.is_active or not user.is_superuser:
        raise PermissionDenied


def _may_use(user, instance=None, target=None):
    """A superuser; or a VM owner with the backup permission, who may change
    instance, on a target open to VM owners."""
    if user is None or not user.is_active:
        raise PermissionDenied
    if user.is_superuser:
        return
    if not user.has_perm("instances.backup_instances"):
        raise PermissionDenied
    if instance is not None:
        from instances.views import get_instance

        if instance.is_template:  # a template is cloned, not backed up by its owner
            raise PermissionDenied
        try:
            get_instance(user, instance.pk, perm_type="change")
        except Http404 as err:
            raise PermissionDenied from err
    if target is not None and not target.owners:
        raise util.OperationError(_("Backup target %(target)s is not open to VM owners"), target=target.name)


def _backup_quota(user, needed):
    """A VM owner's backups by hand (being made: their estimate) and needed
    bytes more stay within their backup quota."""
    if user.is_superuser:
        return
    limit = UserAttributes.objects.get_or_create(user=user)[0].max_backup_size
    if limit < 0:
        return
    used = (Backup.objects.filter(taken_by=user, policy__isnull=True, state__in=Backup.LIVING)
            .aggregate(total=Sum("size"))["total"] or 0)
    if limit == 0:
        raise util.OperationError(_("You have no backup quota; an administrator sets it with your user's quota"))
    if used + needed > limit * 1024**3:
        # in GiB to one decimal, but never 0.0 for a small disk
        gib = lambda size: max(round(size / 1024**3, 1), 0.1) if size else 0
        raise util.OperationError(_("The backup needs about %(needed)s GiB; %(used)s GiB of your %(limit)d GiB backup "
                                    "quota is used"), needed=gib(needed), used=gib(used), limit=limit)


def _vm_pool(instance):
    """The storage pool of the VM's first disk: where its owner's restore as
    a new VM goes."""
    proxy = _proxy(instance)
    path = etree.fromstring(proxy._XMLDesc(PERSISTENT_XML)).xpath("string(devices/disk[@device='disk']/source/@file)")
    return proxy.get_volume_by_path(path).storagePoolLookupByVolume().name()


def _proxy(instance):
    c = instance.compute
    return wvmBackup(c.hostname, c.login, c.password, c.type, instance.name, uuid=instance.uuid)


def _target_row(target, compute):
    row = target.pool_on(compute)
    if row is None:
        raise util.OperationError(_("Backup target %(target)s has no storage pool on %(compute)s"),
                                  target=target.name, compute=compute.name)
    return row


def _check_state(proxy, frozen):
    """A running, paused or shut-off VM is backed up; frozen file systems
    only when its guest agent answers."""
    status = proxy.get_status()
    if status not in (VIR_DOMAIN_RUNNING, VIR_DOMAIN_PAUSED, VIR_DOMAIN_SHUTOFF):
        raise util.OperationError(_("The VM must be running, paused or shut off to be backed up"))
    if status == VIR_DOMAIN_SHUTOFF:
        return
    if proxy.wvm.getLibVersion() < LIVE_CLONE_MIN_LIBVIRT:
        raise util.OperationError(_("A running VM's backup needs libvirt 11.10 or later; shut the VM down to back it up"))
    if frozen and status == VIR_DOMAIN_PAUSED:
        raise util.OperationError(_("A paused VM's file systems cannot be frozen"))
    if frozen and not proxy.is_agent_ready():
        raise util.OperationError(_("The guest agent does not answer: the file systems cannot be frozen"))


def _checked(op):
    """In the worker, before anything is made: the VM and its target pool
    (the one registered)."""
    instance = _instance(op.params["instance"])
    target = BackupTarget.objects.get(pk=op.params["target"])
    _may_use(op.user, instance, target)  # again: rights may have changed since the job was queued
    if instance.compute_id != op.intent["compute"]:
        raise util.OperationError(_("The VM moved to another compute after the job was queued"))
    row = _target_row(target, instance.compute)
    proxy = _proxy(instance)
    pool = target_pool(proxy, row.pool, row.pool_uuid)
    plan = proxy.backup_plan()
    _check_state(proxy, op.params["frozen"])
    # the target claim admits one backup at a time: this check counts every other one of the user's
    _backup_quota(op.user, _estimate(plan))
    return instance, target, row, proxy, pool, plan


def _estimate(plan):
    """A backup's size before it is made: what its disks hold now."""
    return sum(d.get("allocation", 0) for d in plan["disks"])


def _free_space():
    values = _snapshot_free_space()
    return {"free_percent": values.get("free_percent", 10), "free_min_gib": values.get("free_min_gib", 1)}


def _owner():
    return int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID), int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)


def _all_names(names):
    return [*names["disks"].values(), *(n for n in (names["nvram"], names["domain"], names["manifest"]) if n)]


def _nvram(op, proxy):
    """The NVRAM file's bytes, or None when the VM has none or never
    started. A running VM's is kept only when it is the one read before its
    backup began: the guest did not write it across the capture point."""
    path = op.intent["plan"]["nvram"]
    if not path:
        return None
    before = op.intent.get("nvram_before")
    data = proxy.read_nvram(path)
    if not op.intent["live"]:
        return data
    for attempt in range(NVRAM_READS):
        if attempt:
            time.sleep(NVRAM_WAIT)
            data = proxy.read_nvram(path)
        if (hashlib.sha256(data).hexdigest() if data is not None else None) == before:
            return data
    raise util.OperationError(_("The VM's NVRAM file changed while it was backed up; back the VM up again"))


def _chain_parent(policy, instance, target, plan, proxy, pool):
    """The backup a scheduled backup of the VM builds on and the bytes each
    disk changed since, or (None, None) for a full one: the schedule's
    newest ready backup with a checkpoint, in a chain shorter than
    full_every, of the same disks, every file of its chain in the target,
    and its checkpoint's bitmaps whole on the VM."""
    last = (Backup.objects.filter(instance=instance, policy=policy, target=target, state=Backup.READY)
            .exclude(checkpoint="").order_by("-created_at").first())
    chain, backup = [], last
    while backup is not None:
        chain.append(backup)
        backup = backup.parent
    if not chain or len(chain) >= policy.full_every or any(b.state != Backup.READY for b in chain):
        return None, None
    if chain[-1].manifest.get("parent"):  # its base's row is gone: the chain cannot be read whole
        return None, None
    devs = sorted(d["dev"] for d in plan["disks"])
    if sorted(last.files.filter(role=BackupFile.DISK).values_list("dev", flat=True)) != devs:
        return None, None
    pool.refresh(0)
    files = set(BackupFile.objects.filter(backup__in=chain, role=BackupFile.DISK).values_list("volume", flat=True))
    if not files <= set(pool.listVolumes()):
        return None, None
    sizes = proxy.checkpoint_sizes(last.checkpoint, devs)
    return (last, sizes) if sizes is not None else (None, None)


def _prune_checkpoints(op, proxy, plan):
    """The VM's backup checkpoints deleted but each schedule's newest ready
    one, the base of its next incremental backup."""
    backups = Backup.objects.filter(vm_uuid=op.intent["uuid"]).exclude(checkpoint="").exclude(uuid=op.intent["backup"])
    keep = set()
    for policy_id in backups.filter(policy__full_every__gt=1).values_list("policy", flat=True).distinct():
        newest = backups.filter(policy=policy_id, state=Backup.READY).order_by("-created_at").first()
        if newest is not None:
            keep.add(newest.checkpoint)
    known = {b.checkpoint: int(b.created_at.timestamp()) for b in backups}
    proxy.prune_checkpoints(keep=keep, known=known, devs=[d["dev"] for d in plan["disks"]])


def _publish(op, proxy, pool):
    """The copied disks are complete: the NVRAM file, the definition and the
    manifest written and read back, then the row ready with its files.
    Runs again in recovery: each upload replaces its volume."""
    plan, names = op.intent["plan"], op.intent["names"]
    if not op.intent["live"] and proxy.get_status() != VIR_DOMAIN_SHUTOFF:
        # its NVRAM and TPM state would be newer than the disks copied
        raise util.OperationError(_("The VM started while its disks were copied; back it up again"))
    backup = Backup.objects.get(uuid=op.intent["backup"])
    pool.refresh(0)
    files = []
    for disk in plan["disks"]:
        size = pool.storageVolLookupByName(names["disks"][disk["dev"]]).info()[2]
        files.append({"role": BackupFile.DISK, "dev": disk["dev"], "volume": names["disks"][disk["dev"]],
                      "format": disk["format"], "capacity": disk["capacity"], "size": size, "sha256": ""})
    nvram = _nvram(op, proxy)
    if nvram is not None:
        files.append({"role": BackupFile.NVRAM, "dev": "", "volume": names["nvram"], "format": "raw",
                      "capacity": len(nvram), "size": len(nvram), "sha256": put_file(proxy, pool, names["nvram"], nvram, _owner())})
    # a shut-off VM's (a running one with a TPM is refused); a secret: no other user reads it
    tpm = proxy.read_tpm() if plan["tpm"] else None
    for name, data in (tpm or {}).items():
        files.append({"role": BackupFile.TPM, "dev": name, "volume": names["tpm"] + name, "format": "raw",
                      "capacity": len(data), "size": len(data),
                      "sha256": put_file(proxy, pool, names["tpm"] + name, data, _owner(), mode="0600")})
    definition = plan["definition"].encode()
    files.append({"role": BackupFile.DOMAIN, "dev": "", "volume": names["domain"], "format": "", "capacity": len(definition),
                  "size": len(definition), "sha256": put_file(proxy, pool, names["domain"], definition, _owner(),
                                                              mode="0600")})  # it has the graphics passwords
    manifest = {
        "format": MANIFEST_FORMAT,
        "backup": str(backup.uuid),
        "vm": {"name": backup.vm_name, "uuid": backup.vm_uuid},
        "compute": backup.compute_name,
        "created_at": backup.created_at.isoformat(),
        "consistency": op.intent["consistency"],
        "nvram": "copied" if nvram is not None else ("never written" if plan["nvram"] else "none"),
        "parent": str(backup.parent.uuid) if backup.parent else None,
        "checkpoint": backup.checkpoint,
        "tpm": "copied" if tpm else ("never written" if tpm == {} else "none"),
        "files": files,
        "left_out": plan["left_out"],
        "libvirt": proxy.wvm.getLibVersion(),
        "hypervisor": proxy.wvm.getVersion(),
    }
    data = json.dumps(manifest, indent=2, sort_keys=True).encode()
    put_file(proxy, pool, names["manifest"], data, _owner())
    with transaction.atomic():
        backup.files.all().delete()
        BackupFile.objects.bulk_create(BackupFile(backup=backup, **f) for f in files)
        backup.manifest = manifest
        backup.consistency = op.intent["consistency"]
        backup.size = sum(f["size"] for f in files) + len(data)
        backup.state = Backup.READY
        backup.finished_at = timezone.now()
        backup.save()
    return {"backup": str(backup.uuid)}


def _discard(op, pool):
    """The job's files removed, its row failed."""
    pool.refresh(0)  # the TPM state files are named by what the VM had
    names = op.intent["names"]
    remove_files(pool, [*_all_names(names), *(n for n in pool.listVolumes() if n.startswith(names["tpm"]))])
    Backup.objects.filter(uuid=op.intent["backup"]).update(state=Backup.FAILED, finished_at=timezone.now())


@register
class CreateBackup(Kind):
    """A shut-off VM's disks are copied one at a time; a running or paused
    VM's with libvirt's push backup, from one instant (the live clone's)."""

    name = "backup.create"
    label = _("Back up VM")
    cancellable = True  # libvirt aborts a push backup; an offline copy stops before its next disk
    progress_bytes = True

    def normalize(self, raw):
        return {"instance": int(raw["instance"]), "target": int(raw["target"]),
                "frozen": str(raw.get("frozen", "")).lower() in ("1", "true", "on"),
                # the schedule that asked for it, if one did, and the end of its window
                "policy": int(raw["policy"]) if raw.get("policy") else None,
                "deadline": parse_datetime(raw["deadline"]).isoformat() if raw.get("deadline") else None}

    def plan(self, user, params):
        instance = _instance(params["instance"])
        target = BackupTarget.objects.get(pk=params["target"])
        _may_use(user, instance, target)
        if not user.is_superuser and (params["policy"] or params["deadline"]):
            raise PermissionDenied  # only a schedule asks for those
        _target_row(target, instance.compute)
        proxy = _proxy(instance)
        _backup_quota(user, _estimate(proxy.backup_plan()))
        _check_state(proxy, params["frozen"])
        return Plan(
            claims={claims.compute_key(instance.compute_id): Claim.SHARED,
                    claims.instance_key(instance.uuid): Claim.EXCLUSIVE,
                    claims.backup_target_key(target.pk): Claim.EXCLUSIVE,
                    # a VM owner's backups one at a time: each run's quota check sees the others' rows
                    **({} if user.is_superuser else {f"backup_quota:{user.pk}": Claim.EXCLUSIVE})},
            resource=claims.instance_key(instance.uuid),
            label=f"{instance.compute.name}/{instance.name}",
            intent={"compute": instance.compute_id, "uuid": instance.uuid, "backup": str(uuid4()),
                    "target": target.name},
        )

    def run(self, op, ctx):
        instance, target, row, proxy, pool, plan = _checked(op)
        if op.params.get("policy"):
            # after the host's checks, which may have waited for it: a schedule's backup starts in its window,
            # and on no host gone into maintenance (one by hand may)
            if op.params.get("deadline") and timezone.now() > parse_datetime(op.params["deadline"]):
                raise util.OperationError(_("The schedule's window ended before the backup could start"))
            if instance.compute._in_maintenance_now():
                raise util.OperationError(_("%(compute)s went into maintenance before the scheduled backup could "
                                            "start"), compute=instance.compute.name)
        status = proxy.get_status()
        live = status != VIR_DOMAIN_SHUTOFF
        names = backup_file_names(op.intent["backup"], plan["disks"], bool(plan["nvram"]))
        # a schedule deleted since the job was queued: the backup is kept, without it
        policy = BackupPolicy.objects.filter(pk=op.params.get("policy")).first() if op.params.get("policy") else None
        # a running VM's scheduled backup makes a checkpoint the next one builds on (bitmaps need qcow2 disks)
        checkpoint = (f"wvc-{op.intent['backup']}" if live and policy and policy.full_every > 1
                      and all(d["format"] == "qcow2" for d in plan["disks"]) else "")
        parent, changed = _chain_parent(policy, instance, target, plan, proxy, pool) if checkpoint else (None, None)
        # an incremental backup copies the blocks changed since its parent only
        check_target_space(pool, [{"capacity": size} for size in changed.values()] if parent else plan["disks"],
                           **_free_space())
        backing = {f.dev: f.volume for f in parent.files.filter(role=BackupFile.DISK)} if parent else {}
        ctx.record_intent(live=live, plan=plan, names=names, pool=row.pool, pool_uuid=row.pool_uuid,
                          consistency=Backup.OFFLINE if not live else Backup.CRASH, checkpoint=checkpoint,
                          parent=parent.checkpoint if parent else None, backing=backing)
        Backup.objects.create(uuid=op.intent["backup"], target=target, instance=instance, vm_uuid=instance.uuid,
                              vm_name=instance.name, compute_name=instance.compute.name, operation=op, policy=policy,
                              parent=parent, checkpoint=checkpoint, taken_by=op.user,
                              size=_estimate(plan))  # until it is written: the quota counts it
        ctx.set_phase(_("Copying disks"))
        if live:
            return self._run_live(op, ctx, proxy, pool, status)
        try:
            for disk in plan["disks"]:
                op.refresh_from_db(fields=["cancel_requested"])
                if op.cancel_requested:
                    _discard(op, pool)
                    raise Cancelled
                ctx.record_intent(copying=disk["dev"])
                proxy.copy_disk_offline(disk, row.pool, names["disks"][disk["dev"]], *_owner())
                ctx.record_intent(copied=[*op.intent.get("copied", []), disk["dev"]], copying=None)
        except libvirtError as err:  # libvirt answered: the copy failed and ended
            ctx.record_intent(copy_result=[False, safe_text(err)], copying=None)
            raise
        op.refresh_from_db(fields=["cancel_requested"])
        if op.cancel_requested:  # asked during the last disk's copy
            _discard(op, pool)
            raise Cancelled
        ctx.record_intent(copy_result=[True, ""])
        ctx.set_phase(_("Writing the backup's files"))
        return _publish(op, proxy, pool)

    def _run_live(self, op, ctx, proxy, pool, status):
        plan, names = op.intent["plan"], op.intent["names"]
        if plan["nvram"]:
            data = proxy.read_nvram(plan["nvram"])
            ctx.record_intent(nvram_before=hashlib.sha256(data).hexdigest() if data is not None else None)
        if op.params.get("policy"):  # before the backup begins: a stopped worker leaves nothing undone
            _prune_checkpoints(op, proxy, plan)
        ctx.record_intent(made=True)
        targets = proxy.make_live_targets(plan["disks"], op.intent["pool"], names["disks"], *_owner(),
                                          backing=op.intent["backing"])
        ctx.record_intent(paths=[t["path"] for t in targets])
        # a completed result libvirt still holds is of an earlier job
        proxy.discard_backup_result()
        ctx.record_intent(copy_started=True)
        op.refresh_from_db(fields=["cancel_requested"])
        if op.cancel_requested:
            _discard(op, pool)
            raise Cancelled

        # a required freeze is tried even when the agent seems gone: its failure then fails the backup
        freeze = status == VIR_DOMAIN_RUNNING and (op.params["frozen"] or proxy.is_agent_ready())
        thaw_error = None
        try:
            try:
                if freeze:
                    ctx.record_intent(frozen=True)
                    try:
                        proxy.fs_freeze()
                    except libvirtError:
                        if op.params["frozen"]:
                            raise
                        # crash-consistent, as without an agent; a freeze that failed part way may have
                        # frozen some file systems: frozen stays recorded, so the guest is thawed as frozen
                    else:
                        ctx.record_intent(consistency=Backup.FROZEN)
                proxy.begin_clone_backup(targets, incremental=op.intent["parent"],
                                         checkpoint=op.intent["checkpoint"] or None)
            finally:
                if op.intent.get("frozen"):
                    thaw_error = self._thaw(op, ctx, proxy)
        except libvirtError as err:
            # no backup of ours runs: the copy failed (if this read fails, recovery decides)
            if proxy.backup_targets() != set(op.intent["paths"]):
                ctx.record_intent(copy_result=[False, safe_text(err)])
            raise
        op.refresh_from_db(fields=["cancel_requested"])
        if op.cancel_requested:  # the cancel hook may have run before the backup began
            try:
                self.cancel(op)
            except libvirtError:
                pass  # the hook aborted it, or it ended: its result tells

        while proxy.backup_progress() is not None:
            if thaw_error:  # the guest must not stay frozen for the copy: tried at each look
                thaw_error = self._thaw(op, ctx, proxy)
            time.sleep(PROGRESS_EVERY)
        if thaw_error:
            thaw_error = self._thaw(op, ctx, proxy)
        result = proxy.backup_result()
        ctx.record_intent(copy_result=[result[0], safe_text(result[1] or "")] if result else None)
        if result is None:
            raise util.OperationError(_("libvirt has no result of the copy"))  # recovery decides
        if not result[0]:
            _discard(op, pool)
            if thaw_error:  # the guest is still frozen: recovery thaws it first, a cancelled job would not
                raise util.OperationError(THAW_FAILED, error=thaw_error, vm=op.resource_label.rpartition("/")[2])
            op.refresh_from_db(fields=["cancel_requested"])
            if op.cancel_requested:
                raise Cancelled
            raise util.OperationError(result[1] or _("The copy failed"))
        ctx.set_phase(_("Writing the backup's files"))
        done = _publish(op, proxy, pool)
        if thaw_error:  # the backup is ready; recovery keeps trying to thaw the guest
            raise util.OperationError(THAW_FAILED, error=thaw_error, vm=op.resource_label.rpartition("/")[2])
        return done

    @staticmethod
    def _thaw(op, ctx, proxy):
        """Thaws the guest; its error, or None once thawed."""
        try:
            proxy.fs_thaw()
        except libvirtError as err:  # frozen stays recorded
            ctx.set_phase(_("The guest's file systems could not be thawed; trying again"))
            return err
        ctx.record_intent(frozen=False)
        return None

    def progress(self, op):
        if op.intent.get("live"):
            return _proxy(_instance(op.params["instance"])).backup_progress() if op.intent.get("copy_started") else None
        disks = op.intent.get("plan", {}).get("disks", [])
        copied = set(op.intent.get("copied", []))
        return sum(d["capacity"] for d in disks if d["dev"] in copied), sum(d["capacity"] for d in disks)

    def cancel(self, op):
        # an offline copy stops before its next disk (run checks the request)
        if not op.intent.get("live"):
            return
        proxy = _proxy(_instance(op.params["instance"]))
        paths = set(op.intent.get("paths", []))
        if paths and proxy.backup_targets() == paths:
            proxy.abort_backup()

    def reconcile(self, op):
        backup = Backup.objects.filter(uuid=op.intent["backup"]).first()
        if backup is None:  # the row comes before any file
            return Outcome(Operation.FAILED, error=say(_("The job stopped before the copy started")))
        instance = Instance.objects.select_related("compute").filter(pk=op.params["instance"]).first()
        ended = Operation.CANCELLED if op.cancel_requested else Operation.FAILED
        names = ", ".join(_all_names(op.intent["names"]))
        proxy = None
        if instance is not None and instance.compute_id == op.intent["compute"]:
            try:
                proxy = _proxy(instance)
            except libvirtError as err:
                if err.get_error_code() != VIR_ERR_NO_DOMAIN:
                    raise  # unreachable: recovery waits and retries

        thawed = []
        if op.intent.get("frozen") and proxy is not None:  # thawed first, before anything else
            status = proxy.get_status()
            if status == VIR_DOMAIN_RUNNING:
                proxy.fs_thaw()  # a failure raises: recovery waits and tries again
            elif status == VIR_DOMAIN_PAUSED:  # libvirt thaws no paused guest
                thawed = say(PAUSED_FROZEN, vm=op.resource_label.rpartition("/")[2])
        if backup.state == Backup.READY:
            return Outcome(Operation.SUCCEEDED, result={"backup": str(backup.uuid), **({"warning": thawed} if thawed else {})})

        if proxy is None:
            Backup.objects.filter(pk=backup.pk).update(state=Backup.FAILED, finished_at=timezone.now())
            return Outcome(Operation.UNCERTAIN, error=say(_(
                "The VM is no longer on the compute the job ran on; check these volumes of the backup target, "
                "then resolve this job: %(volumes)s"), volumes=names))
        # after the thaw: an unreachable target must not keep a guest frozen
        pool = target_pool(proxy, op.intent["pool"], op.intent["pool_uuid"])
        outcome = self._outcome(op, proxy, pool, ended, names)
        if outcome.state == Operation.SUCCEEDED and thawed:
            outcome.result["warning"] = thawed
        else:
            outcome.error += thawed
        return outcome

    def _outcome(self, op, proxy, pool, ended, names):
        result = op.intent.get("copy_result")
        if not op.intent["live"]:
            if result is None and op.intent.get("copying"):
                Backup.objects.filter(uuid=op.intent["backup"]).update(state=Backup.FAILED, finished_at=timezone.now())
                return Outcome(Operation.UNCERTAIN, error=say(_(
                    "A disk was being copied when the job stopped; check these volumes of the backup target, then "
                    "resolve this job: %(volumes)s"), volumes=names))
        elif op.intent.get("copy_started") and result is None:
            targets = proxy.backup_targets()
            paths = set(op.intent["paths"])
            if targets == paths:
                return Outcome(Operation.RUNNING, phase=_("libvirt is still copying the disks"),
                               progress=proxy.backup_progress())
            if targets is not None:
                return Outcome(Operation.UNCERTAIN, error=say(_(
                    "Another backup runs on the VM; check these volumes of the backup target, then resolve this "
                    "job: %(volumes)s"), volumes=names))
            result = proxy.backup_result()
            if result is None:
                Backup.objects.filter(uuid=op.intent["backup"]).update(state=Backup.FAILED, finished_at=timezone.now())
                return Outcome(Operation.UNCERTAIN, error=say(_(
                    "libvirt has no result of the copy; check these volumes of the backup target, then resolve this "
                    "job: %(volumes)s"), volumes=names))
        elif op.intent.get("made") and not op.intent.get("paths"):
            # the push backup's volumes were being made: they are named from the backup, so removed by name
            result = [False, ""]
        if result is None or not result[0]:
            _discard(op, pool)
            return Outcome(ended, error=say(result[1]) if result and result[1] else
                           say(_("The job stopped before the copy ended")))
        try:
            return Outcome(Operation.SUCCEEDED, result=_publish(op, proxy, pool))
        except util.ConnectionFailed:
            raise  # unreachable: recovery waits and retries
        except libvirtError as err:  # it would fail the same way at every retry
            _discard(op, pool)
            return Outcome(Operation.FAILED, error=say(_("The backup's files could not be written: %(error)s"), error=err))

    def log_entry(self, op, state):
        if state == Operation.SUCCEEDED:
            action = f"backed up to {op.intent['target']} ({op.intent.get('consistency', '')})"
        else:
            action = f"back up to {op.intent['target']}"
        return _log(op, state, action)


def _target_pool(target):
    """(connection, pool) of the target through the first of its computes
    that reaches its pool."""
    for row in target.pools.select_related("compute").order_by("compute__name"):
        c = row.compute
        try:
            conn = wvmConnect(c.hostname, c.login, c.password, c.type)
            return conn, target_pool(conn, row.pool, row.pool_uuid)
        except libvirtError:
            continue
    raise util.OperationError(_("No compute of backup target %(target)s reaches its storage pool"), target=target.name)


def _target_claims(target):
    """A job on a target alone: the target, and its computes shared, which
    the worker counts so a hung host takes no more than its share of slots."""
    keys = {claims.compute_key(compute_id): Claim.SHARED
            for compute_id in target.pools.values_list("compute_id", flat=True)}
    keys[claims.backup_target_key(target.pk)] = Claim.EXCLUSIVE
    return keys


def _backup(params):
    return Backup.objects.select_related("target").get(uuid=params["backup"])


def beyond_keep(policy, instance_id):
    """A schedule's backups of a VM beyond what it keeps, newest first: the
    ready ones past keep, and the missing ones older than the oldest kept
    (keep counts ready ones only; a missing one would pin its chain)."""
    rows = list(Backup.objects.filter(policy=policy, instance_id=instance_id, state__in=(Backup.READY, Backup.MISSING))
                .order_by("-created_at"))
    ready = [b for b in rows if b.state == Backup.READY]
    if len(ready) <= policy.keep:
        return []
    return [b for b in rows if b.created_at < ready[policy.keep - 1].created_at]


def _beyond_keep(backup, policy_id):
    """Whether the schedule still exists and the backup is still beyond what
    it keeps (keep raised, or a newer one gone, since the deletion was queued)."""
    policy = BackupPolicy.objects.filter(pk=policy_id).first()
    if policy is None or backup.policy_id != policy.pk or backup.instance_id is None or backup.depended_on():
        return False
    return backup.pk in {b.pk for b in beyond_keep(policy, backup.instance_id)}


@register
class DeleteBackup(Kind):
    """The manifest goes first, so the target no longer holds a complete
    backup; then the other files of the backup, then its row."""

    name = "backup.delete"
    label = _("Delete backup")

    def normalize(self, raw):
        # retention: the schedule whose keep the backup is beyond, when the schedule asks
        return {"backup": str(UUID(str(raw["backup"]))),
                "retention": int(raw["retention"]) if raw.get("retention") else None}

    @staticmethod
    def _may_delete(user, backup):
        """A superuser; or a VM owner with the backup permission, a backup
        they took by hand."""
        _may_use(user)
        if not user.is_superuser and (backup.taken_by_id != user.pk or backup.policy_id is not None):
            raise PermissionDenied
        _may_use(user, target=backup.target)

    def plan(self, user, params):
        backup = _backup(params)
        self._may_delete(user, backup)
        if backup.being_made:
            raise util.OperationError(_("This backup is being made; cancel its job to stop it"))
        if backup.depended_on():
            raise util.OperationError(_("Later backups depend on this one; delete them first"))
        return Plan(
            claims={claims.backup_key(backup.uuid): Claim.EXCLUSIVE, **_target_claims(backup.target)},
            resource=claims.backup_key(backup.uuid),
            label=f"{backup.vm_name} {timezone.localtime(backup.created_at):%Y-%m-%d %H:%M}",
            intent={"compute": backup.compute_name, "vm": backup.vm_name, "uuid": backup.vm_uuid,
                    "time": timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M")},
        )

    def run(self, op, ctx):
        backup = _backup(op.params)
        self._may_delete(op.user, backup)
        _conn, pool = _target_pool(backup.target)
        # after reaching the target, right before deleting: a schedule's keep may have been raised meanwhile
        if op.params.get("retention") and not _beyond_keep(backup, op.params["retention"]):
            raise util.OperationError(_("The backup is no longer beyond what its schedule keeps; it is kept"))
        if backup.depended_on():  # made since the deletion was queued: the target claim now holds it off
            raise util.OperationError(_("Later backups depend on this one; delete them first"))
        ctx.record_intent(deleting=True)
        return self._delete(backup, pool)

    @staticmethod
    def _delete(backup, pool):
        Backup.objects.filter(pk=backup.pk).update(state=Backup.DELETING)
        # another compute may have written the files: this one's pool lists them after a refresh
        pool.refresh(0)
        manifest = f"{backup.prefix}-manifest.json"
        remove_files(pool, [manifest])
        remove_files(pool, [n for n in pool.listVolumes() if n.startswith(backup.prefix + "-") and n != manifest])
        backup.delete()
        return {}

    def reconcile(self, op):
        if not op.intent.get("deleting"):  # stopped before it began: the rights it checks are not checked here
            return Outcome(Operation.FAILED, error=say(_("The job stopped before the deletion began")))
        backup = Backup.objects.select_related("target").filter(uuid=op.params["backup"]).first()
        if backup is None:
            return Outcome(Operation.SUCCEEDED)
        return Outcome(Operation.SUCCEEDED, result=self._delete(backup, _target_pool(backup.target)[1]))

    def log_entry(self, op, state):
        backup = f"Backup {op.intent['time']} of {op.intent['vm']}"
        message = f"{backup} deleted" if state == Operation.SUCCEEDED else f"{backup}: delete ({state})"
        return op.intent["compute"], op.intent["vm"], op.intent["uuid"], message


def _connect(compute):
    return wvmConnect(compute.hostname, compute.login, compute.password, compute.type)


def _check_name(name):
    """A new VM's name, as the clone's."""
    if Instance.objects.filter(name=name).exists():
        raise util.OperationError(_("Instance '%(clone_name)s' already exists!"), clone_name=name)
    if len(name) > 64:
        raise util.OperationError(_("Instance name '%(clone_name)s' is longer than 64 characters"), clone_name=name)
    if not re.fullmatch(r"[a-zA-Z0-9-]+", name):
        raise util.OperationError(_("Instance name '%(clone_name)s' contains invalid characters!"), clone_name=name)


def _check_files(conn, pool, files):
    """Each file of a backup ({role, volume, capacity, sha256}) is in the
    target: disks at their size, the small files with their SHA-256."""
    pool.refresh(0)
    for f in files:
        try:
            vol = pool.storageVolLookupByName(f["volume"])
        except libvirtError as err:
            if err.get_error_code() != VIR_ERR_NO_STORAGE_VOL:
                raise
            raise util.OperationError(_("The backup's file %(name)s is missing from the target"), name=f["volume"]) from err
        if f["role"] == BackupFile.DISK:
            if vol.info()[1] != f["capacity"]:
                raise util.OperationError(_("The backup's file %(name)s differs from the one written"), name=f["volume"])
        elif hashlib.sha256(get_file(conn, pool, f["volume"])).hexdigest() != f["sha256"]:
            raise util.OperationError(_("The backup's file %(name)s differs from the one written"), name=f["volume"])


def _base_files(backup, dev=None):
    """The disk files of the backups an incremental backup builds on (of
    the disk dev only, when given), checked as its own before a restore
    copies the chain flat. Refuses a chain whose base's row is gone."""
    files = []
    while True:
        if backup.parent_id is None:
            if backup.manifest.get("parent"):
                raise util.OperationError(_("The backup taken %(time)s builds on a backup that is gone"),
                                          time=timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M"))
            return files
        backup = backup.parent
        disks = backup.files.filter(role=BackupFile.DISK, **({"dev": dev} if dev else {}))
        files += disks.values("role", "volume", "capacity", "sha256")


def _tpm_files(backup):
    """The backup's TPM state files; a manifest read from a target names
    them: each is a file of the VM's state directory only."""
    files = list(backup.files.filter(role=BackupFile.TPM).order_by("dev"))
    for f in files:
        if not f.dev or "/" in f.dev or f.dev.startswith("."):
            raise util.OperationError(_("The backup's TPM state file %(name)s is not a plain file name"), name=f.dev)
    return files


@register
class RestoreBackup(Kind):
    """A ready backup made a new VM on a compute that has the target's pool:
    its disks copied from the target into one of the compute's pools, its
    NVRAM file and TPM state into libvirt's directories, then the VM
    defined, last."""

    name = "backup.restore"
    label = _("Restore backup")
    progress_bytes = True

    def normalize(self, raw):
        return {"backup": str(UUID(str(raw["backup"]))), "compute": int(raw["compute"]),
                "pool": str(raw.get("pool", "")).strip(), "name": str(raw.get("name", "")).strip(),
                "connect": str(raw.get("connect", "")).lower() in ("1", "true", "on"),
                "start": str(raw.get("start", "")).lower() in ("1", "true", "on")}

    @staticmethod
    def _owner_quota(user, params, backup):
        """For a VM owner: the backup is of a VM they may change, restored on
        its compute into its first disk's pool, within their quota. What the
        new VM adds to the quota, None for a superuser."""
        _may_use(user, backup.instance, backup.target)
        if user.is_superuser:
            return None
        if backup.instance is None:
            raise PermissionDenied
        if params["compute"] != backup.instance.compute_id or params["pool"] != _vm_pool(backup.instance):
            raise PermissionDenied
        compute = backup.instance.compute
        conn = _connect(compute)
        row = _target_row(backup.target, compute)
        tree = etree.fromstring(get_file(conn, target_pool(conn, row.pool, row.pool_uuid),
                                         backup.files.get(role=BackupFile.DOMAIN).volume))
        memory = int(tree.findtext("memory")) * {"KiB": 1, "MiB": 1024, "GiB": 1024**2}.get(
            tree.find("memory").get("unit", "KiB"), 1) // 1024
        disk = sum(f.capacity >> 30 for f in backup.files.filter(role=BackupFile.DISK))
        quota = {"cpus": int(tree.findtext("vcpu")), "memory": memory, "disk": disk}
        exceeded = check_user_quota(user, 1, quota["cpus"], quota["memory"], quota["disk"])
        if exceeded == QUOTA_UNVERIFIED:
            raise util.OperationError(QUOTA_UNVERIFIED_TEXT)
        if exceeded:
            raise util.OperationError(_("%(quota)s: cannot restore %(name)s"), quota=quota_message(exceeded),
                                      name=params["name"])
        return quota

    def plan(self, user, params):
        backup = _backup(params)
        if backup.state != Backup.READY:
            raise util.OperationError(_("Only a ready backup is restored"))
        quota = self._owner_quota(user, params, backup)
        compute = Compute.objects.get(pk=params["compute"])
        _target_row(backup.target, compute)
        compute.refuse_new_vms()
        _check_name(params["name"])
        volumes = {f.dev: f"{params['name']}-{f.dev}.{'qcow2' if f.format == 'qcow2' else 'raw'}"
                   for f in backup.files.filter(role=BackupFile.DISK)}
        keys = vm_claims(compute, params["name"])
        for name in volumes.values():  # no other job makes a volume of these names meanwhile
            keys[claims.volume_key(compute.pk, params["pool"], name)] = Claim.EXCLUSIVE
        keys[claims.backup_key(backup.uuid)] = Claim.SHARED
        keys[claims.backup_target_key(backup.target_id)] = Claim.EXCLUSIVE
        if quota:  # a VM owner's: no other increase of their quota is admitted until the VM is recorded
            keys[claims.quota_key(user.pk)] = Claim.EXCLUSIVE
        return Plan(
            claims=keys,
            resource=claims.backup_key(backup.uuid),
            label=f"{compute.name}/{params['name']}",
            intent={"compute": compute.pk, "uuid": str(uuid4()), "name": params["name"], "from": backup.vm_name,
                    "volumes": volumes, "pool": params["pool"], **({"quota": quota} if quota else {}),
                    "time": timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M")},
        )

    def run(self, op, ctx):
        p = op.params
        backup = _backup(p)
        # the rights again; the quota was taken at admission: the job counts in it until its VM is recorded
        _may_use(op.user, backup.instance if not op.user.is_superuser else None, backup.target)
        if not op.user.is_superuser and (backup.instance is None or p["compute"] != backup.instance.compute_id
                                         or p["pool"] != _vm_pool(backup.instance)):
            raise PermissionDenied  # the VM moved since the job was queued: the owner's restore follows it
        compute = Compute.objects.get(pk=p["compute"])
        compute.refuse_new_vms()
        _check_name(p["name"])
        conn = _connect(compute)
        if p["name"] in conn.get_instances():
            raise util.OperationError(_("A VM named %(name)s exists on %(compute)s"), name=p["name"], compute=compute.name)
        row = _target_row(backup.target, compute)
        tpool = target_pool(conn, row.pool, row.pool_uuid)
        _check_files(conn, tpool, [*backup.files.values("role", "volume", "capacity", "sha256"), *_base_files(backup)])
        definition = get_file(conn, tpool, backup.files.get(role=BackupFile.DOMAIN).volume).decode()
        check_restore_host(conn, definition)
        pools = conn.file_pools()
        if p["pool"] not in pools:
            raise util.OperationError(_("This host has no active directory storage pool %(pool)s"), pool=p["pool"])
        dest = pools[p["pool"]][0]
        disks = list(backup.files.filter(role=BackupFile.DISK).order_by("dev"))
        check_target_space(dest, [{"capacity": d.capacity} for d in disks], **_free_space())
        volumes = op.intent["volumes"]
        for name in volumes.values():
            wvmInstance._refuse_taken(dest, name)
        nvram_file = backup.files.filter(role=BackupFile.NVRAM).first()
        tree = etree.fromstring(definition)
        old_nvram = tree.xpath("string(os/nvram/source/@file)") or (tree.findtext("os/nvram") or "").strip()
        # the VM's own file in libvirt's directory; libvirt makes it from the template when none was kept
        nvram = os.path.join(NVRAM_DIR, p["name"] + "_VARS" + os.path.splitext(old_nvram)[1]) if old_nvram else None
        macs = [get_random_mac_address() for _nic in tree.findall("devices/interface")]
        tpm_files = _tpm_files(backup)
        if nvram:
            # a file of that name may be a removed VM's kept one, or another VM's: never taken, never removed
            with conn._nvram_pool() as nvram_pool:
                if volume_exists(nvram_pool, os.path.basename(nvram)):
                    raise util.OperationError(_("The NVRAM file %(path)s exists already"), path=nvram)

        # what the VM is made of, before anything is made: recovery finds and removes it by these
        ctx.record_intent(nvram=nvram, macs=macs, tpm=bool(tpm_files))
        ctx.set_phase(_("Copying disks"))
        storage = wvmStorage(compute.hostname, compute.login, compute.password, compute.type, p["pool"])
        paths = {}
        for disk in disks:
            ctx.record_intent(copying=disk.dev)
            try:
                paths[disk.dev] = storage.clone_volume(tpool.storageVolLookupByName(disk.volume), volumes[disk.dev],
                                                       vol_fmt=disk.format, disk_owner_uid=_owner()[0],
                                                       disk_owner_gid=_owner()[1])
            except libvirtError:  # libvirt answered: the copy failed; its claimed name goes with the copies
                ctx.record_intent(copied=[*op.intent.get("copied", []), disk.dev], copying=None)
                raise
            ctx.record_intent(copied=[*op.intent.get("copied", []), disk.dev], copying=None)
        if nvram and nvram_file:
            data = get_file(conn, tpool, nvram_file.volume)
            with conn._nvram_pool() as nvram_pool:
                # QEMU's, as the clone's copy: qemu may run without libvirt changing a file's owner
                conn.upload_volume(nvram_pool, os.path.basename(nvram), data, owner=_owner(), mode="0600")
        if tpm_files:
            with conn._tpm_pool(op.intent["uuid"], build=True) as tpm_pool:
                for f in tpm_files:
                    # root's: libvirt makes the state directory swtpm's when the VM starts
                    conn.upload_volume(tpm_pool, f.dev, get_file(conn, tpool, f.volume), owner=(0, 0), mode="0600")

        compute.refuse_new_vms()  # again: the host may have gone in maintenance while the disks were copied
        xml = restore_definition(definition, name=p["name"], uuid=op.intent["uuid"], macs=macs,
                                 disks={d.dev: (paths[d.dev], d.format) for d in disks}, nvram=nvram,
                                 connect=p["connect"])
        conn.wvm.defineXML(xml)
        record_vm(op, owner=True)
        result = {"open": _vm_page(op)}
        if p["start"]:
            try:
                compute.refuse_start()
                conn.wvm.lookupByUUIDString(op.intent["uuid"]).create()
            except libvirtError as err:
                result["warning"] = say(_("The VM was restored; it did not start: %(error)s"), error=err)
        return result

    def progress(self, op):
        disks = Backup.objects.filter(uuid=op.params["backup"]).values_list("files__dev", "files__capacity", "files__role")
        copied = set(op.intent.get("copied", []))
        sizes = {dev: capacity for dev, capacity, role in disks if role == BackupFile.DISK}
        return sum(c for dev, c in sizes.items() if dev in copied), sum(sizes.values())

    def reconcile(self, op):
        compute = Compute.objects.get(pk=op.intent["compute"])
        conn = _connect(compute)
        try:
            conn.wvm.lookupByUUIDString(op.intent["uuid"])
        except libvirtError as err:
            if err.get_error_code() != VIR_ERR_NO_DOMAIN:
                raise  # unreachable: recovery waits and retries
        else:  # defined last: the restore is done, but for the start it was asked for
            record_vm(op, owner=True)
            result = {"open": _vm_page(op)}
            dom = conn.wvm.lookupByUUIDString(op.intent["uuid"])
            if op.params["start"] and not dom.isActive():
                try:
                    compute.refuse_start()
                    dom.create()
                except (libvirtError, util.OperationError) as err:
                    result["warning"] = say(_("The VM was restored; it did not start: %(error)s"), error=err)
            return Outcome(Operation.SUCCEEDED, result=result)
        if op.intent.get("copying"):  # libvirt's answer to that copy is unknown
            return Outcome(Operation.UNCERTAIN, error=say(_(
                "A disk was being copied when the job stopped; check this volume, then resolve this job: %(volumes)s"),
                volumes=op.intent["volumes"][op.intent["copying"]]))
        if copied := [op.intent["volumes"][dev] for dev in op.intent.get("copied", [])]:
            pools = conn.file_pools()
            if op.intent["pool"] not in pools:  # recovery waits: the copies are removed once it runs
                raise util.OperationError(_("Storage pool %(pool)s is not active; the restore's copies in it are "
                                            "removed when it is"), pool=op.intent["pool"])
            pool = pools[op.intent["pool"]][0]
            pool.refresh(0)
            remove_files(pool, copied)
        if nvram := op.intent.get("nvram"):
            with conn._nvram_pool() as nvram_pool:
                remove_files(nvram_pool, [os.path.basename(nvram)])
        if op.intent.get("tpm"):
            # the new UUID's directory: only this job wrote in it (its empty directories stay)
            with conn._tpm_pool(op.intent["uuid"]) as tpm_pool:
                if tpm_pool is not None:
                    remove_files(tpm_pool, tpm_pool.listVolumes())
        ended = Operation.CANCELLED if op.cancel_requested else Operation.FAILED
        return Outcome(ended, error=say(_("The VM was not defined; its copies were removed")))

    def log_entry(self, op, state):
        return _log(op, state, f"restored from the backup of {op.intent['from']} taken {op.intent['time']}")


def _over_plan(backup, proxy, owner=False):
    """What a restore over the backup's VM replaces: {"disks": {dev: the
    disk's pool}, "old": {dev: the disk's path now}, "nvram": the VM's NVRAM
    path or None, "tpm": bool}.
    Refuses a VM that is not shut off, has snapshots, or whose disks, UEFI
    firmware or TPM are not the backup's."""
    if proxy.get_status() != VIR_DOMAIN_SHUTOFF:
        raise util.OperationError(_("Shut the VM down to restore a backup over it"))
    if proxy.instance.snapshotNum(0):
        # their metadata names the disks that are replaced
        raise util.OperationError(_("The VM has snapshots; delete them to restore a backup over it"))
    plan = proxy.backup_plan()
    files = {f.dev: f for f in backup.files.filter(role=BackupFile.DISK)}
    now = {d["dev"]: d for d in plan["disks"]}
    if set(now) != set(files):
        raise util.OperationError(_("The VM's disks (%(now)s) are not the backup's (%(then)s); restore it as a new VM "
                                    "or one disk"), now=", ".join(sorted(now)), then=", ".join(sorted(files)))
    for dev, f in files.items():  # a VM owner's disk quota counts the VM's disks as they are now
        if owner and f.capacity > now[dev]["capacity"]:
            raise util.OperationError(_("The backup's disk %(dev)s is larger than the VM's now; restore it as a new VM"),
                                      dev=dev)
    if bool(plan["nvram"]) != (backup.manifest.get("nvram", "none") != "none"):
        raise util.OperationError(_("The VM's UEFI firmware changed since the backup; restore it as a new VM"))
    if plan["tpm"] != (backup.manifest.get("tpm", "none") != "none"):
        raise util.OperationError(_("The VM's TPM changed since the backup; restore it as a new VM"))
    return {"disks": {dev: now[dev]["pool"] for dev in files},
            "old": {dev: now[dev]["path"] for dev in files}, "nvram": plan["nvram"], "tpm": plan["tpm"]}


def _over_names(backup, proxy, over):
    """The copies' volume names, {dev: name}: the VM's, the disk's and the
    backup's time, numbered from 2 when its pool has that name (the backup
    restored over the VM before, or another one of the same minute)."""
    time = timezone.localtime(backup.created_at).strftime("%Y%m%d-%H%M")
    pools = proxy.file_pools()
    names = {}
    for f in backup.files.filter(role=BackupFile.DISK):
        pool = pools.get(over["disks"][f.dev])
        if pool:
            pool[0].refresh(0)
        taken = set(pool[0].listVolumes()) if pool else set()
        base, ext = f"{proxy.instance.name()}-{f.dev}-{time}", "qcow2" if f.format == "qcow2" else "raw"
        names[f.dev] = next(name for name in itertools.chain([f"{base}.{ext}"], (f"{base}-{n}.{ext}" for n in itertools.count(2)))
                            if name not in taken)
    return names


@register
class RestoreOver(Kind):
    """A ready backup restored over its own shut-off VM: its disks copied as
    new volumes beside the VM's (kept until removed by hand), then the
    switch: the NVRAM file and TPM state replaced and the VM's definition
    pointed at the copies. The rest of the definition stays the VM's."""

    name = "backup.restore_over"
    label = _("Restore backup over the VM")
    progress_bytes = True

    def normalize(self, raw):
        return {"backup": str(UUID(str(raw["backup"])))}

    def plan(self, user, params):
        backup = _backup(params)
        if backup.state != Backup.READY:
            raise util.OperationError(_("Only a ready backup is restored"))
        instance = backup.instance
        if instance is None:
            _may_use(user)
            raise util.OperationError(_("The backup's VM is no longer in the panel; restore it as a new VM"))
        _may_use(user, instance, backup.target)
        _target_row(backup.target, instance.compute)
        proxy = _proxy(instance)
        over = _over_plan(backup, proxy, owner=not user.is_superuser)
        names = _over_names(backup, proxy, over)
        keys = {claims.compute_key(instance.compute_id): Claim.SHARED, claims.instance_key(instance.uuid): Claim.EXCLUSIVE,
                claims.backup_key(backup.uuid): Claim.SHARED, claims.backup_target_key(backup.target_id): Claim.EXCLUSIVE}
        for dev, name in names.items():  # no other job makes a volume of these names meanwhile
            keys[claims.volume_key(instance.compute_id, over["disks"][dev], name)] = Claim.EXCLUSIVE
        return Plan(
            claims=keys,
            resource=claims.instance_key(instance.uuid),
            label=f"{instance.compute.name}/{instance.name}",
            intent={"compute": instance.compute_id, "uuid": instance.uuid, "over": over, "names": names,
                    "time": timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M")},
        )

    def run(self, op, ctx):
        backup = _backup(op.params)
        instance = _instance(backup.instance_id)
        _may_use(op.user, instance, backup.target)
        if instance.compute_id != op.intent["compute"]:
            raise util.OperationError(MOVED)
        proxy = _proxy(instance)
        if _over_plan(backup, proxy, owner=not op.user.is_superuser) != op.intent["over"]:
            raise util.OperationError(_("The VM's disks changed after the job was queued"))
        row = _target_row(backup.target, instance.compute)
        tpool = target_pool(proxy, row.pool, row.pool_uuid)
        _check_files(proxy, tpool, [*backup.files.values("role", "volume", "capacity", "sha256"), *_base_files(backup)])
        _tpm_files(backup)
        disks = {f.dev: f for f in backup.files.filter(role=BackupFile.DISK)}
        pools = proxy.file_pools()
        over, names = op.intent["over"], op.intent["names"]
        for dev, name in names.items():
            if over["disks"][dev] not in pools:
                raise util.OperationError(_("This host has no active directory storage pool %(pool)s"),
                                          pool=over["disks"][dev])
            wvmInstance._refuse_taken(pools[over["disks"][dev]][0], name)
        for pool in set(over["disks"].values()):
            check_target_space(pools[pool][0], [{"capacity": disks[dev].capacity} for dev, p in over["disks"].items()
                                                if p == pool], **_free_space())

        ctx.set_phase(_("Copying disks"))
        c = instance.compute
        paths = {}
        for dev, name in names.items():
            ctx.record_intent(copying=dev)
            storage = wvmStorage(c.hostname, c.login, c.password, c.type, over["disks"][dev])
            try:
                paths[dev] = storage.clone_volume(tpool.storageVolLookupByName(disks[dev].volume), name,
                                                  vol_fmt=disks[dev].format, disk_owner_uid=_owner()[0],
                                                  disk_owner_gid=_owner()[1])
            except libvirtError:  # libvirt answered: its claimed name is removed with the copies
                ctx.record_intent(copied=[*op.intent.get("copied", []), dev], copying=None)
                raise
            ctx.record_intent(copied=[*op.intent.get("copied", []), dev], paths=paths, copying=None)

        # the VM may have been started or saved outside the panel meanwhile: then it keeps its disks
        if _over_plan(backup, proxy, owner=not op.user.is_superuser) != op.intent["over"]:
            raise util.OperationError(_("The VM changed while its backup was copied; it keeps its disks"))
        # an owner cannot remove the old disks: they go once the VM no longer names them
        remove = [] if op.user.is_superuser else list(op.intent["over"]["old"].values())
        ctx.set_phase(_("Replacing the VM's disks"))
        ctx.record_intent(switching=True, autostart=bool(proxy.instance.autostart()), remove=remove)
        return self._switch(op, backup, proxy, tpool)

    @staticmethod
    def _switch(op, backup, proxy, tpool):
        """The NVRAM file and TPM state replaced, the disks' sources set; runs
        again in recovery until it is done."""
        over = op.intent["over"]
        # a host booting mid-switch starts nothing: the old disks with the backup's NVRAM and TPM would not match
        proxy.instance.setAutostart(0)
        # the disks are replaced: their bitmaps are not the VM's any more, the next scheduled backup is full
        proxy.drop_checkpoint_metadata()
        if over["nvram"]:
            nvram = backup.files.filter(role=BackupFile.NVRAM).first()
            with proxy._nvram_pool() as nvram_pool:
                remove_files(nvram_pool, [os.path.basename(over["nvram"])])
                if nvram is not None:  # else never written: libvirt makes it from the template
                    proxy.upload_volume(nvram_pool, os.path.basename(over["nvram"]), get_file(proxy, tpool, nvram.volume),
                                        owner=_owner(), mode="0600")
        if over["tpm"]:
            files = _tpm_files(backup)
            with proxy._tpm_pool(op.intent["uuid"], build=bool(files)) as tpm_pool:
                if tpm_pool is not None:  # swtpm's .lock stays
                    remove_files(tpm_pool, [n for n in tpm_pool.listVolumes() if not n.startswith(".")])
                    for f in files:  # root's: libvirt makes them swtpm's when the VM starts
                        proxy.upload_volume(tpm_pool, f.dev, get_file(proxy, tpool, f.volume), owner=(0, 0), mode="0600")
        disks = {f.dev: (op.intent["paths"][f.dev], f.format) for f in backup.files.filter(role=BackupFile.DISK)}
        proxy._defineXML(restore_over_definition(proxy._XMLDesc(PERSISTENT_XML), disks))
        if op.intent["autostart"]:
            proxy.instance.setAutostart(1)
        RestoreOver._remove_old(op, proxy, backup.instance)
        return {"open": reverse("instances:instance", args=[backup.instance_id])}

    @staticmethod
    def _remove_old(op, proxy, instance):
        """The disks the VM ran from, after the switch, when its owner restored
        it; one another domain uses, checked right before, is kept."""
        paths = op.intent.get("remove", [])
        if not paths:
            return
        used = proxy.paths_used_by_other_domains(paths) | paths_used_on_other_computes(instance.compute, paths)
        for path in (path for path in paths if path not in used):
            try:
                proxy.get_volume_by_path(path).delete(0)
            except libvirtError as err:
                if err.get_error_code() != VIR_ERR_NO_STORAGE_VOL:
                    raise

    def progress(self, op):
        disks = Backup.objects.filter(uuid=op.params["backup"]).values_list("files__dev", "files__capacity", "files__role")
        copied = set(op.intent.get("copied", []))
        sizes = {dev: capacity for dev, capacity, role in disks if role == BackupFile.DISK}
        return sum(c for dev, c in sizes.items() if dev in copied), sum(sizes.values())

    def reconcile(self, op):
        backup = _backup(op.params)
        instance = Instance.objects.select_related("compute").get(pk=backup.instance_id)
        if instance.compute_id != op.intent["compute"]:
            return Outcome(Operation.UNCERTAIN, error=say(_(
                "The VM moved to another compute; check its disks and the restore's copies, then resolve this job")))
        proxy = _proxy(instance)
        if op.intent.get("switching"):
            current = etree.fromstring(proxy._XMLDesc(PERSISTENT_XML))
            if {d.find("target").get("dev"): d.xpath("string(source/@file)")
                    for d in current.xpath("devices/disk[@device='disk']")} == op.intent["paths"]:
                # defined: the switch is done; the VM may have run since, its NVRAM and TPM are not replaced again
                if op.intent["autostart"]:
                    proxy.instance.setAutostart(1)
                self._remove_old(op, proxy, instance)
                return Outcome(Operation.SUCCEEDED, result={"open": reverse("instances:instance", args=[instance.pk])})
            if proxy.get_status() != VIR_DOMAIN_SHUTOFF or proxy.instance.hasManagedSaveImage(0):
                return Outcome(Operation.UNCERTAIN, error=say(_(
                    "The VM was started while its disks were being replaced; check its disks, then resolve this job")))
            row = _target_row(backup.target, instance.compute)
            return Outcome(Operation.SUCCEEDED,
                           result=self._switch(op, backup, proxy, target_pool(proxy, row.pool, row.pool_uuid)))
        volumes = op.intent["names"]
        if op.intent.get("copying"):  # libvirt's answer to that copy is unknown
            return Outcome(Operation.UNCERTAIN, error=say(_(
                "A disk was being copied when the job stopped; check this volume, then resolve this job: %(volumes)s"),
                volumes=volumes[op.intent["copying"]]))
        pools = proxy.file_pools()
        for dev in op.intent.get("copied", []):
            pool = op.intent["over"]["disks"][dev]
            if pool not in pools:  # recovery waits: the copies are removed once it runs
                raise util.OperationError(_("Storage pool %(pool)s is not active; the restore's copies in it are "
                                            "removed when it is"), pool=pool)
            pools[pool][0].refresh(0)
            remove_files(pools[pool][0], [volumes[dev]])
        ended = Operation.CANCELLED if op.cancel_requested else Operation.FAILED
        return Outcome(ended, error=say(_("The VM keeps its disks; the restore's copies were removed")))

    def log_entry(self, op, state):
        return _log(op, state, f"restored over from its backup taken {op.intent['time']}")


@register
class RestoreDisk(Kind):
    """One disk of a ready backup copied as a new volume into a pool of a
    compute that has the target's pool; attached to no VM."""

    name = "backup.restore_disk"
    label = _("Restore a disk of a backup")
    progress_bytes = True

    def normalize(self, raw):
        return {"backup": str(UUID(str(raw["backup"]))), "dev": str(raw["dev"]).strip(), "compute": int(raw["compute"]),
                "pool": str(raw.get("pool", "")).strip(), "name": str(raw.get("name", "")).strip()}

    @staticmethod
    def _disk(backup, params):
        disk = backup.files.filter(role=BackupFile.DISK, dev=params["dev"]).first()
        if disk is None:
            raise util.OperationError(_("The backup has no disk %(dev)s"), dev=params["dev"])
        return disk

    def plan(self, user, params):
        _superuser(user)
        backup = _backup(params)
        if backup.state != Backup.READY:
            raise util.OperationError(_("Only a ready backup is restored"))
        self._disk(backup, params)
        if not params["name"] or "/" in params["name"] or params["name"].startswith("."):
            raise util.OperationError(_("%(name)s is not a volume name"), name=params["name"])
        compute = Compute.objects.get(pk=params["compute"])
        _target_row(backup.target, compute)
        return Plan(
            claims={claims.compute_key(compute.pk): Claim.SHARED,
                    claims.volume_key(compute.pk, params["pool"], params["name"]): Claim.EXCLUSIVE,
                    claims.backup_key(backup.uuid): Claim.SHARED,
                    claims.backup_target_key(backup.target_id): Claim.EXCLUSIVE},
            resource=claims.backup_key(backup.uuid),
            label=f"{compute.name}/{backup.vm_name}",
            intent={"compute": compute.pk, "uuid": backup.vm_uuid,
                    "time": timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M")},
        )

    def run(self, op, ctx):
        _superuser(op.user)
        p = op.params
        backup = _backup(p)
        disk = self._disk(backup, p)
        compute = Compute.objects.get(pk=p["compute"])
        conn = _connect(compute)
        row = _target_row(backup.target, compute)
        tpool = target_pool(conn, row.pool, row.pool_uuid)
        _check_files(conn, tpool, [{"role": disk.role, "volume": disk.volume, "capacity": disk.capacity, "sha256": ""},
                                   *_base_files(backup, disk.dev)])
        pools = conn.file_pools()
        if p["pool"] not in pools:
            raise util.OperationError(_("This host has no active directory storage pool %(pool)s"), pool=p["pool"])
        dest = pools[p["pool"]][0]
        wvmInstance._refuse_taken(dest, p["name"])
        check_target_space(dest, [{"capacity": disk.capacity}], **_free_space())
        ctx.set_phase(_("Copying disks"))
        ctx.record_intent(copying=True)
        storage = wvmStorage(compute.hostname, compute.login, compute.password, compute.type, p["pool"])
        try:
            storage.clone_volume(tpool.storageVolLookupByName(disk.volume), p["name"], vol_fmt=disk.format,
                                 disk_owner_uid=_owner()[0], disk_owner_gid=_owner()[1])
        except libvirtError:  # libvirt answered: the copy failed; a volume it made is removed (its name is the job's)
            dest.refresh(0)
            remove_files(dest, [p["name"]])
            ctx.record_intent(copying=False)
            raise
        ctx.record_intent(copying=False, copied=True)
        return self._result(op)

    @staticmethod
    def _result(op):
        return {"open": reverse("storage", args=[op.params["compute"], op.params["pool"]])}

    def progress(self, op):
        capacity = Backup.objects.filter(uuid=op.params["backup"], files__dev=op.params["dev"]).values_list(
            "files__capacity", flat=True).first() or 0
        return (capacity if op.intent.get("copied") else 0), capacity

    def reconcile(self, op):
        if op.intent.get("copied"):
            return Outcome(Operation.SUCCEEDED, result=self._result(op))
        if op.intent.get("copying"):  # libvirt's answer to the copy is unknown
            return Outcome(Operation.UNCERTAIN, error=say(_(
                "The disk was being copied when the job stopped; check this volume, then resolve this job: %(volume)s"),
                volume=op.params["name"]))
        ended = Operation.CANCELLED if op.cancel_requested else Operation.FAILED
        return Outcome(ended, error=say(_("The disk was not restored")))

    def log_entry(self, op, state):
        p = op.params
        return _log(op, state, f"disk {p['dev']} of the backup taken {op.intent['time']} restored as {p['name']} "
                               f"in {p['pool']}")


def _vm_page(op):
    vm = Instance.objects.get(compute_id=op.intent["compute"], uuid=op.intent["uuid"])
    return reverse("instances:instance", args=[vm.pk])


@register
class ImportBackups(Kind):
    """The backups of a target read into the panel, as after the panel's
    database was lost: each manifest whose backup the panel does not list
    is checked as a restore checks it, then added with its files. Nothing
    on the target changes."""

    name = "backup.import"
    label = _("Read backups from target")

    def normalize(self, raw):
        return {"target": int(raw["target"])}

    def plan(self, user, params):
        _superuser(user)
        target = BackupTarget.objects.get(pk=params["target"])
        return Plan(claims=_target_claims(target),
                    resource=claims.backup_target_key(target.pk), label=target.name, intent={"target": target.name})

    def run(self, op, ctx):
        _superuser(op.user)
        target = BackupTarget.objects.get(pk=op.params["target"])
        conn, pool = _target_pool(target)
        added, incomplete, manifests = 0, [], []
        for name in manifest_names(pool):
            try:
                data = get_file(conn, pool, name)
            except libvirtError:  # unreadable (its permissions, a broken file): the others are still read
                incomplete.append(name)
                continue
            try:
                manifests.append((parse_datetime(json.loads(data)["created_at"]), name, data))
            except (ValueError, KeyError, TypeError):
                manifests.append((None, name, data))  # passed over below
        # oldest first: an incremental backup's base is read before it
        manifests.sort(key=lambda m: m[0].timestamp() if m[0] else 0)
        for _created_at, name, data in manifests:
            try:
                manifest = json.loads(data)
                if manifest["format"] != MANIFEST_FORMAT:
                    raise ValueError(manifest["format"])
                if Backup.objects.filter(uuid=manifest["backup"]).exists():
                    continue
                parent = None
                if manifest.get("parent"):
                    parent = Backup.objects.filter(uuid=manifest["parent"]).first()
                    if parent is None:  # its base was not read: it cannot be restored
                        raise ValueError(manifest["parent"])
                roles = [f["role"] for f in manifest["files"]]
                if roles.count(BackupFile.DOMAIN) != 1 or BackupFile.DISK not in roles:
                    raise ValueError(roles)  # a restore needs the definition and a disk
                _check_files(conn, pool, manifest["files"])
                files = [{k: f[k] for k in ("role", "dev", "volume", "format", "capacity", "size", "sha256")}
                         for f in manifest["files"]]
                vm, created_at = manifest["vm"], parse_datetime(manifest["created_at"])
                if created_at is None:
                    raise ValueError(manifest["created_at"])
                fields = {"vm_uuid": vm["uuid"], "vm_name": vm["name"], "compute_name": manifest["compute"],
                          "consistency": manifest["consistency"], "parent": parent,
                          "checkpoint": manifest.get("checkpoint") or ""}
            except (ValueError, KeyError, TypeError, ValidationError, util.OperationError):
                # cut short, not a manifest of the panel, or a file missing or changed: the others are still read
                incomplete.append(name)
                continue
            with transaction.atomic():
                backup = Backup.objects.create(
                    uuid=manifest["backup"], target=target, state=Backup.READY, **fields,
                    instance=Instance.objects.filter(uuid=fields["vm_uuid"]).first(),
                    manifest=manifest, finished_at=timezone.now(), size=sum(f["size"] for f in files) + len(data),
                )
                # the time it was taken, not read
                Backup.objects.filter(pk=backup.pk).update(created_at=created_at)
                BackupFile.objects.bulk_create(BackupFile(backup=backup, **f) for f in files)
            added += 1
        result = {"added": added, "open": reverse("vmbackups:target", args=[target.pk])}
        if incomplete:
            result["warning"] = say(_("Not read, as a file of the backup is missing, changed or unreadable: %(names)s"),
                                    names=", ".join(incomplete))
        return result

    def log_entry(self, op, state):
        message = f"Backup target {op.intent['target']}: backups read"
        return "-", "", "", message if state == Operation.SUCCEEDED else f"{message} ({state})"


@register
class CheckTarget(Kind):
    """A target's backups checked against its pool: a ready backup with a
    file gone (its manifest too) becomes missing, a missing one whose files
    are all there ready again. A pool no compute reaches marks nothing."""

    name = "backup.check"
    label = _("Check backup target")

    def normalize(self, raw):
        return {"target": int(raw["target"])}

    def plan(self, user, params):
        _superuser(user)
        target = BackupTarget.objects.get(pk=params["target"])
        return Plan(claims=_target_claims(target),
                    resource=claims.backup_target_key(target.pk), label=target.name, intent={"target": target.name})

    def run(self, op, ctx):
        _superuser(op.user)
        target = BackupTarget.objects.get(pk=op.params["target"])
        _conn, pool = _target_pool(target)
        pool.refresh(0)
        present = set(pool.listVolumes())
        settled = timezone.now() - CHECK_SETTLE
        missing = []
        for backup in target.backups.filter(state__in=(Backup.READY, Backup.MISSING)).prefetch_related("files"):
            needed = {f.volume for f in backup.files.all()} | {f"{backup.prefix}-manifest.json"}
            try:
                needed |= {f["volume"] for f in _base_files(backup)}  # a restore copies the chain flat
                state = Backup.READY if needed <= present else Backup.MISSING
            except util.OperationError:  # its base's row is gone
                state = Backup.MISSING
            if state == Backup.MISSING and backup.state == Backup.READY and (backup.finished_at or settled) > settled:
                continue  # just written through another compute: this one may not list its files yet (NFS)
            if state == Backup.MISSING:
                missing.append(f"{backup.vm_name} {timezone.localtime(backup.created_at):%Y-%m-%d %H:%M}")
            # only from the state read: a deletion begun meanwhile is left alone
            Backup.objects.filter(pk=backup.pk, state=backup.state).update(state=state)
        BackupTarget.objects.filter(pk=target.pk).update(checked_at=timezone.now())
        if missing:
            return {"warning": say(_("Files of these backups are missing from the target: %(backups)s"),
                                   backups=", ".join(missing))}
        return {}

    def log_entry(self, op, state):
        message = f"Backup target {op.intent['target']}: checked"
        return "-", "", "", message if state == Operation.SUCCEEDED else f"{message} ({state})"


from .schedule import run_schedules  # noqa: E402 (it submits this module's kinds)

register_periodic(run_schedules)
