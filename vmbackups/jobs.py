"""Jobs of the vmbackups app (operations framework)."""

import hashlib
import json
import time
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_noop as _
from libvirt import VIR_DOMAIN_PAUSED, VIR_DOMAIN_RUNNING, VIR_DOMAIN_SHUTOFF, VIR_ERR_NO_DOMAIN, libvirtError

from appsettings.settings import app_settings
from instances.jobs import PAUSED_FROZEN, THAW_FAILED, _instance, _log, _snapshot_free_space
from instances.models import Instance
from operations import claims
from operations.jobs import Cancelled, Kind, Outcome, Plan, register
from operations.models import Claim, Operation
from operations.utils import safe_text, say
from vrtManager import util
from vrtManager.backup import backup_file_names, check_target_space, put_file, remove_files, target_pool, wvmBackup
from vrtManager.instance import LIVE_CLONE_MIN_LIBVIRT

from .models import Backup, BackupFile, BackupTarget

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
                "frozen": str(raw.get("frozen", "")).lower() in ("1", "true", "on")}

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
        status = proxy.get_status()
        live = status != VIR_DOMAIN_SHUTOFF
        names = backup_file_names(op.intent["backup"], plan["disks"], bool(plan["nvram"]))
        ctx.record_intent(live=live, plan=plan, names=names, pool=row.pool, pool_uuid=row.pool_uuid,
                          consistency=Backup.OFFLINE if not live else Backup.CRASH)
        Backup.objects.create(uuid=op.intent["backup"], target=target, instance=instance, vm_uuid=instance.uuid,
                              vm_name=instance.name, compute_name=instance.compute.name, operation=op)
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
