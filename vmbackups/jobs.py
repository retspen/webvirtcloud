"""Jobs of the vmbackups app (operations framework)."""

import hashlib
import json
import os
import re
import time
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_noop as _
from lxml import etree
from libvirt import VIR_DOMAIN_PAUSED, VIR_DOMAIN_RUNNING, VIR_DOMAIN_SHUTOFF, VIR_ERR_NO_DOMAIN, VIR_ERR_NO_STORAGE_VOL, libvirtError

from appsettings.settings import app_settings
from computes.models import Compute
from instances.jobs import PAUSED_FROZEN, THAW_FAILED, _instance, _log, _snapshot_free_space, record_vm, vm_claims
from instances.utils import get_random_mac_address
from instances.models import Instance
from operations import claims
from operations.jobs import Cancelled, Kind, Outcome, Plan, register, register_periodic
from operations.models import Claim, Operation
from operations.utils import safe_text, say
from vrtManager import util
from vrtManager.backup import (backup_file_names, check_restore_host, check_target_space, get_file, manifest_names, put_file,
                               remove_files, restore_definition, target_pool, volume_exists, wvmBackup)
from vrtManager.connection import NVRAM_DIR, wvmConnect
from vrtManager.instance import wvmInstance
from vrtManager.storage import wvmStorage
from vrtManager.instance import LIVE_CLONE_MIN_LIBVIRT

from .models import Backup, BackupFile, BackupPolicy, BackupTarget

MANIFEST_FORMAT = 1
NVRAM_READS = 3  # a running VM's NVRAM read after its backup, until it is the one read before
NVRAM_WAIT = 5  # seconds between those reads
PROGRESS_EVERY = 2  # seconds between reads of a push backup's progress


def _superuser(user):
    if user is None or not user.is_active or not user.is_superuser:
        raise PermissionDenied


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
    """In the worker, before anything is made: the VM, its target pool (the
    one registered) and the space for its disks."""
    _superuser(op.user)
    instance = _instance(op.params["instance"])
    if instance.compute_id != op.intent["compute"]:
        raise util.OperationError(_("The VM moved to another compute after the job was queued"))
    target = BackupTarget.objects.get(pk=op.params["target"])
    row = _target_row(target, instance.compute)
    proxy = _proxy(instance)
    pool = target_pool(proxy, row.pool, row.pool_uuid)
    plan = proxy.backup_plan()
    _check_state(proxy, op.params["frozen"])
    check_target_space(pool, plan["disks"], **_free_space())
    return instance, target, row, proxy, pool, plan


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


def _publish(op, proxy, pool):
    """The copied disks are complete: the NVRAM file, the definition and the
    manifest written and read back, then the row ready with its files.
    Runs again in recovery: each upload replaces its volume."""
    plan, names = op.intent["plan"], op.intent["names"]
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
    definition = plan["definition"].encode()
    files.append({"role": BackupFile.DOMAIN, "dev": "", "volume": names["domain"], "format": "", "capacity": len(definition),
                  "size": len(definition), "sha256": put_file(proxy, pool, names["domain"], definition, _owner())})
    manifest = {
        "format": MANIFEST_FORMAT,
        "backup": str(backup.uuid),
        "vm": {"name": backup.vm_name, "uuid": backup.vm_uuid},
        "compute": backup.compute_name,
        "created_at": backup.created_at.isoformat(),
        "consistency": op.intent["consistency"],
        "nvram": "copied" if nvram is not None else ("never written" if plan["nvram"] else "none"),
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
    remove_files(pool, _all_names(op.intent["names"]))
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
        _superuser(user)
        instance = _instance(params["instance"])
        target = BackupTarget.objects.get(pk=params["target"])
        _target_row(target, instance.compute)
        proxy = _proxy(instance)
        proxy.backup_plan()
        _check_state(proxy, params["frozen"])
        return Plan(
            claims={claims.compute_key(instance.compute_id): Claim.SHARED,
                    claims.instance_key(instance.uuid): Claim.EXCLUSIVE,
                    claims.backup_target_key(target.pk): Claim.EXCLUSIVE},
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
        ctx.record_intent(live=live, plan=plan, names=names, pool=row.pool, pool_uuid=row.pool_uuid,
                          consistency=Backup.OFFLINE if not live else Backup.CRASH)
        # a schedule deleted since the job was queued: the backup is kept, without it
        policy = BackupPolicy.objects.filter(pk=op.params.get("policy")).first() if op.params.get("policy") else None
        Backup.objects.create(uuid=op.intent["backup"], target=target, instance=instance, vm_uuid=instance.uuid,
                              vm_name=instance.name, compute_name=instance.compute.name, operation=op, policy=policy)
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
        ctx.record_intent(copy_result=[True, ""])
        ctx.set_phase(_("Writing the backup's files"))
        return _publish(op, proxy, pool)

    def _run_live(self, op, ctx, proxy, pool, status):
        plan, names = op.intent["plan"], op.intent["names"]
        if plan["nvram"]:
            data = proxy.read_nvram(plan["nvram"])
            ctx.record_intent(nvram_before=hashlib.sha256(data).hexdigest() if data is not None else None)
        ctx.record_intent(made=True)
        targets = proxy.make_live_targets(plan["disks"], op.intent["pool"], names["disks"], *_owner())
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
                proxy.begin_clone_backup(targets)
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


def _beyond_keep(backup, policy_id):
    """Whether the schedule still exists and the backup is still one of its
    VM's ready backups beyond what it keeps (keep raised, or a newer one gone,
    since the deletion was queued)."""
    policy = BackupPolicy.objects.filter(pk=policy_id).first()
    if policy is None or backup.policy_id != policy.pk or backup.instance_id is None:
        return False
    ready = list(Backup.objects.filter(policy=policy, instance_id=backup.instance_id, state=Backup.READY)
                 .order_by("-created_at").values_list("pk", flat=True))
    return backup.pk in ready[policy.keep:]


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

    def plan(self, user, params):
        _superuser(user)
        backup = _backup(params)
        if backup.state == Backup.CREATING:
            raise util.OperationError(_("This backup is being made; cancel its job to stop it"))
        return Plan(
            claims={claims.backup_key(backup.uuid): Claim.EXCLUSIVE, **_target_claims(backup.target)},
            resource=claims.backup_key(backup.uuid),
            label=f"{backup.target.name}/{backup.vm_name}",
            intent={"compute": backup.compute_name, "vm": backup.vm_name, "uuid": backup.vm_uuid,
                    "time": timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M")},
        )

    def run(self, op, ctx):
        _superuser(op.user)
        backup = _backup(op.params)
        if op.params.get("retention") and not _beyond_keep(backup, op.params["retention"]):
            raise util.OperationError(_("The backup is no longer beyond what its schedule keeps; it is kept"))
        _conn, pool = _target_pool(backup.target)
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


@register
class RestoreBackup(Kind):
    """A ready backup made a new VM on a compute that has the target's pool:
    its disks copied from the target into one of the compute's pools, its
    NVRAM file into libvirt's directory, then the VM defined, last."""

    name = "backup.restore"
    label = _("Restore backup")
    progress_bytes = True

    def normalize(self, raw):
        return {"backup": str(UUID(str(raw["backup"]))), "compute": int(raw["compute"]),
                "pool": str(raw.get("pool", "")).strip(), "name": str(raw.get("name", "")).strip(),
                "connect": str(raw.get("connect", "")).lower() in ("1", "true", "on"),
                "start": str(raw.get("start", "")).lower() in ("1", "true", "on")}

    def plan(self, user, params):
        _superuser(user)
        backup = _backup(params)
        if backup.state != Backup.READY:
            raise util.OperationError(_("Only a ready backup is restored"))
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
        return Plan(
            claims=keys,
            resource=claims.backup_key(backup.uuid),
            label=f"{compute.name}/{params['name']}",
            intent={"compute": compute.pk, "uuid": str(uuid4()), "name": params["name"], "from": backup.vm_name,
                    "volumes": volumes, "pool": params["pool"],
                    "time": timezone.localtime(backup.created_at).strftime("%Y-%m-%d %H:%M")},
        )

    def run(self, op, ctx):
        _superuser(op.user)
        p = op.params
        backup = _backup(p)
        compute = Compute.objects.get(pk=p["compute"])
        compute.refuse_new_vms()
        _check_name(p["name"])
        conn = _connect(compute)
        if p["name"] in conn.get_instances():
            raise util.OperationError(_("A VM named %(name)s exists on %(compute)s"), name=p["name"], compute=compute.name)
        row = _target_row(backup.target, compute)
        tpool = target_pool(conn, row.pool, row.pool_uuid)
        _check_files(conn, tpool, backup.files.values("role", "volume", "capacity", "sha256"))
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
        if nvram:
            # a file of that name may be a removed VM's kept one, or another VM's: never taken, never removed
            with conn._nvram_pool() as nvram_pool:
                if volume_exists(nvram_pool, os.path.basename(nvram)):
                    raise util.OperationError(_("The NVRAM file %(path)s exists already"), path=nvram)

        # what the VM is made of, before anything is made: recovery finds and removes it by these
        ctx.record_intent(nvram=nvram, macs=macs)
        ctx.set_phase(_("Copying disks"))
        storage = wvmStorage(compute.hostname, compute.login, compute.password, compute.type, p["pool"])
        paths = {}
        for disk in disks:
            ctx.record_intent(copying=disk.dev)
            paths[disk.dev] = storage.clone_volume(tpool.storageVolLookupByName(disk.volume), volumes[disk.dev],
                                                   vol_fmt=disk.format, disk_owner_uid=_owner()[0],
                                                   disk_owner_gid=_owner()[1])
            ctx.record_intent(copied=[*op.intent.get("copied", []), disk.dev], copying=None)
        if nvram and nvram_file:
            data = get_file(conn, tpool, nvram_file.volume)
            with conn._nvram_pool() as nvram_pool:
                # QEMU's, as the clone's copy: qemu may run without libvirt changing a file's owner
                conn.upload_volume(nvram_pool, os.path.basename(nvram), data, owner=_owner(), mode="0600")

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
        else:  # defined last: the restore is done
            record_vm(op, owner=True)
            return Outcome(Operation.SUCCEEDED, result={"open": _vm_page(op)})
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
        ended = Operation.CANCELLED if op.cancel_requested else Operation.FAILED
        return Outcome(ended, error=say(_("The VM was not defined; its copies were removed")))

    def log_entry(self, op, state):
        return _log(op, state, f"restored from the backup of {op.intent['from']} taken {op.intent['time']}")


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
        added, incomplete = 0, []
        for name in manifest_names(pool):
            data = get_file(conn, pool, name)
            try:
                manifest = json.loads(data)
                if manifest["format"] != MANIFEST_FORMAT:
                    raise ValueError(manifest["format"])
                if Backup.objects.filter(uuid=manifest["backup"]).exists():
                    continue
                _check_files(conn, pool, manifest["files"])
                files = [{k: f[k] for k in ("role", "dev", "volume", "format", "capacity", "size", "sha256")}
                         for f in manifest["files"]]
                vm, created_at = manifest["vm"], parse_datetime(manifest["created_at"])
                if created_at is None:
                    raise ValueError(manifest["created_at"])
                fields = {"vm_uuid": vm["uuid"], "vm_name": vm["name"], "compute_name": manifest["compute"],
                          "consistency": manifest["consistency"]}
            except (ValueError, KeyError, TypeError, util.OperationError):
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
        result = {"added": added}
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
        missing = []
        for backup in target.backups.filter(state__in=(Backup.READY, Backup.MISSING)).prefetch_related("files"):
            needed = {f.volume for f in backup.files.all()} | {f"{backup.prefix}-manifest.json"}
            state = Backup.READY if needed <= present else Backup.MISSING
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
