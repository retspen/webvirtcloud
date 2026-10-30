"""Jobs of the instances app (operations framework, spec section 5)."""

import math
import os
import re
import time

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils.translation import gettext_noop
from django.utils.translation import gettext_noop as _
from libvirt import (VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE, VIR_DOMAIN_JOB_NONE, VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL,
                     VIR_ERR_NO_DOMAIN, VIR_ERR_NO_STORAGE_VOL, libvirtError)
from lxml import etree
from vrtManager import util
from vrtManager.connection import wvmConnect
from vrtManager.create import cpu_choices, wvmCreate
from vrtManager.instance import HOST_DEVICES, check_snapshot_name, wvmInstance
from vrtManager.nodedevs import check_hostdevs

from accounts.models import UserInstance, UserSSHKey
from appsettings.settings import app_settings
from computes.models import Compute
from instances import utils
from instances.models import Instance
from operations import claims
from operations.jobs import Cancelled, Kind, Outcome, Plan, register
from operations.models import Claim, Operation


def _authorized(user, pk):
    """The instance views' rule: change access and the snapshot permission."""
    from instances.views import get_instance

    if user is None or not user.is_active:
        raise PermissionDenied
    instance = get_instance(user, pk, perm_type="change")
    if not user.has_perm("instances.snapshot_instances"):
        raise PermissionDenied
    return instance


def _proxy(instance):
    c = instance.compute
    return wvmInstance(c.hostname, c.login, c.password, c.type, instance.name, uuid=instance.uuid)


def _instance(pk):
    return Instance.objects.select_related("compute").get(pk=pk)


def _vm_plan(params):
    """A job on one VM: the VM exclusive, its compute shared."""
    instance = _instance(params["instance"])
    return Plan(
        claims={claims.compute_key(instance.compute_id): Claim.SHARED,
                claims.instance_key(instance.uuid): Claim.EXCLUSIVE},
        resource=claims.instance_key(instance.uuid),
        label=f"{instance.compute.name}/{instance.name}",
        intent={"compute": instance.compute_id, "uuid": instance.uuid},
    )


def _checked_proxy(op):
    """In the worker: the user may still change the VM, and it did not move."""
    instance = _authorized(op.user, op.params["instance"])
    if instance.compute_id != op.intent["compute"]:
        raise util.OperationError("The VM moved to another compute after the job was queued")
    return _proxy(instance)


def _recovery_proxy(op):
    """The VM for recovery; None when it left the compute the job ran on."""
    instance = Instance.objects.select_related("compute").filter(pk=op.params["instance"]).first()
    if instance is None or instance.compute_id != op.intent.get("compute"):
        return None
    try:
        return _proxy(instance)
    except libvirtError as err:
        if err.get_error_code() == VIR_ERR_NO_DOMAIN:
            return None
        raise  # unreachable: recovery waits and retries


def _libvirt_busy(dom):
    """libvirt still runs a job on the VM that the worker no longer waits for."""
    return dom.isActive() and dom.jobInfo()[0] != VIR_DOMAIN_JOB_NONE


def _log(op, state, action, vm=None):
    """The job's row: "VM <name>: <action>", the end state added unless it succeeded."""
    compute, _sep, label_vm = op.resource_label.rpartition("/")  # a VM name has no "/"
    vm = vm or label_vm
    message = f"VM {vm}: {action}"
    return compute, vm, op.intent["uuid"], message if state == Operation.SUCCEEDED else f"{message} ({state})"


def _snapshot_free_space():
    """The free space each storage pool keeps for a snapshot, from the
    Settings page; an invalid value leaves the backend's default."""
    values = {}
    for key, argument in (("SNAPSHOT_FREE_SPACE_PERCENT", "free_percent"), ("SNAPSHOT_FREE_SPACE_MIN_GIB", "free_min_gib")):
        try:
            value = float(getattr(app_settings, key))
        except (AttributeError, TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            values[argument] = value
    return values


CLONE_POST_KEY_RE = re.compile(r"^(clone-net-mac-\d+|disk-[a-z0-9]+|meta-[a-z0-9]+)$")
CLONE_FIELDS = ("name", "clone-title", "clone-description")


def clone_data(user, instance, fields):
    """The clone's settings from the form fields and the source as it is now;
    OperationError with the reason when it cannot be made."""
    from instances.views import VOLUME_NAME_RE, quota_refused

    data = dict()
    data["name"] = fields.get("name", "").strip()
    data["clone-title"] = fields.get("clone-title", "").strip()
    data["clone-description"] = fields.get("clone-description", "").strip()

    # the clone copies the disks of the persistent definition
    disk_sum = sum(int(disk.get("size") or 0) >> 30 for disk in instance.config_disks)
    quota_msg = utils.check_user_quota(user, 1, instance.vcpu, instance.memory, disk_sum)

    data["disk_owner_uid"] = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
    data["disk_owner_gid"] = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)

    # Only superusers may choose disk names and MAC addresses; the form only
    # shows those fields to them.
    if user.is_superuser:
        for key, value in fields.items():
            if CLONE_POST_KEY_RE.fullmatch(key):
                data[key] = value.strip()

    if app_settings.CLONE_INSTANCE_AUTO_NAME == "True" and not data["name"]:
        auto_vname = utils.get_clone_free_names()[0]
        data["name"] = auto_vname
        for disk in instance.config_disks:
            data[f"disk-{disk['dev']}"] = utils.get_clone_disk_name(disk, instance.name, auto_vname)

    if not user.is_superuser:
        for disk in instance.config_disks:
            data[f"disk-{disk['dev']}"] = utils.get_clone_disk_name(disk, instance.name, data["name"])
        for num in range(len(instance.config_networks)):
            key = f"clone-net-mac-{num}"
            if not data.get(key):
                data[key] = (utils.get_dhcp_mac_address(data["name"]) if num == 0 else "") or utils.get_random_mac_address()

    check_instance = Instance.objects.filter(name=data["name"])
    invalid_macs = [
        value for key, value in data.items()
        if key.startswith("clone-net-mac-") and not utils.MAC_ADDRESS_RE.fullmatch(value)
    ]
    invalid_disks = [
        value for key, value in data.items()
        # None: a disk without a volume, which clone_instance does not copy.
        if key.startswith("disk-") and value is not None and not VOLUME_NAME_RE.fullmatch(value)
    ]

    if not user.is_superuser and quota_msg:
        raise util.OperationError(quota_refused(quota_msg, _(
            "User '%(quota_msg)s' quota reached, cannot create '%(clone_name)s'!"
        ) % {"quota_msg": quota_msg, "clone_name": data["name"]}))
    if check_instance:
        raise util.OperationError(_("Instance '%(clone_name)s' already exists!") % {"clone_name": data["name"]})
    if not re.match(r"^[a-zA-Z0-9-]+$", data["name"]):
        raise util.OperationError(
            _("Instance name '%(clone_name)s' contains invalid characters!") % {"clone_name": data["name"]})
    if invalid_macs:
        raise util.OperationError(_("Instance MAC '%(clone_mac)s' invalid format!") % {"clone_mac": ", ".join(invalid_macs)})
    if invalid_disks:
        raise util.OperationError(
            _("Disk name '%(disk_name)s' contains invalid characters!") % {"disk_name": ", ".join(str(v) for v in invalid_disks)})
    return data


def vm_claims(compute, name):
    """A job that adds a VM: other VMs stay usable; the VM list reconcile waits."""
    return {claims.compute_key(compute.pk): Claim.SHARED, claims.reconcile_key(compute.pk): Claim.EXCLUSIVE,
            claims.name_key(compute.pk, name): Claim.EXCLUSIVE}


def record_vm(op, owner):
    """The panel's records of the new VM, as the synchronous views wrote them."""
    vm = Instance.objects.get_or_create(compute_id=op.intent["compute"], uuid=op.intent["uuid"],
                                        defaults={"name": op.intent["name"]})[0]
    if owner and op.user_id:
        UserInstance.objects.get_or_create(instance=vm, user_id=op.user_id,
                                           defaults={"is_delete": True, "is_change": True, "is_vnc": True})


def vm_outcome(op, owner, volumes):
    """The VM is defined last: if it exists, the job succeeded. If it does not and
    none of its planned volumes exists either, the job failed and changed nothing."""
    c = Compute.objects.get(pk=op.intent["compute"])
    conn = wvmConnect(c.hostname, c.login, c.password, c.type).wvm
    try:
        conn.lookupByUUIDString(op.intent["uuid"])
    except libvirtError as err:
        if err.get_error_code() != VIR_ERR_NO_DOMAIN:
            raise  # unreachable: recovery waits and retries
        held = set()
        for pool in conn.listAllStoragePools(VIR_CONNECT_LIST_STORAGE_POOLS_ACTIVE):
            held.update(pool.listVolumes())
        left = sorted(held & set(volumes))
        if not left:
            return Outcome(Operation.FAILED, error="The VM was not defined and no volume of it was left.")
        return Outcome(Operation.UNCERTAIN,
                       error=f"The VM was not defined; check these volumes, then resolve this job: {', '.join(left)}")
    record_vm(op, owner)
    return Outcome(Operation.SUCCEEDED)


def _clonable(user, pk):
    from instances.views import _clone_source

    if user is None or not user.has_perm("instances.clone_instances"):
        raise PermissionDenied
    return _clone_source(user, pk)


def _merged(jobs):
    """(done, total) bytes of the snapshot's block jobs."""
    return sum(j["cur"] for j in jobs), sum(j["end"] for j in jobs)


@register
class DeleteExternalSnapshot(Kind):
    name = "snapshot.delete"
    label = gettext_noop("Delete snapshot")
    time_limit = 6 * 3600  # a merge cannot be stopped: over time is only noted
    progress_bytes = True  # libvirt block job cur/end

    def normalize(self, raw):
        return {"instance": int(raw["instance"]), "name": str(raw.get("name", ""))}

    def validate(self, user, params):
        instance = _authorized(user, params["instance"])
        if params["name"] not in _proxy(instance).instance.snapshotListNames(VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL):
            raise util.OperationError(f"The VM has no external snapshot named {params['name']}")

    def plan(self, user, params):
        return _vm_plan(params)

    def precheck(self, op, ctx):
        proxy = _checked_proxy(op)
        proxy._snapshot(op.params["name"], external=True)
        proxy._check_snapshot_state()

    def run(self, op, ctx):
        proxy = _proxy(_instance(op.params["instance"]))
        ctx.record_intent(before=proxy.snapshot_files_state())
        ctx.set_phase(gettext_noop("Merging the snapshot"))
        return {"left_behind": proxy.delete_external_snapshot(op.params["name"])}

    def progress(self, op):
        jobs = _proxy(_instance(op.params["instance"])).get_snapshot_jobs()
        return _merged(jobs) if jobs else None

    def reconcile(self, op):
        instance = Instance.objects.select_related("compute").filter(pk=op.params["instance"]).first()
        if instance is None or instance.compute_id != op.intent.get("compute"):
            return Outcome(Operation.UNCERTAIN, error="The VM is no longer on the compute the job ran on")
        try:
            proxy = _proxy(instance)
            listed = op.params["name"] in proxy.instance.snapshotListNames(VIR_DOMAIN_SNAPSHOT_LIST_EXTERNAL)
            jobs = proxy.get_snapshot_jobs()
        except util.ConnectionFailed:
            raise  # unreachable: recovery waits and retries
        except libvirtError as err:  # OperationError is a libvirtError too
            if err.get_error_code() == VIR_ERR_NO_DOMAIN:
                return Outcome(Operation.UNCERTAIN, error="The VM is no longer on its compute")
            raise
        if jobs:
            return Outcome(Operation.RUNNING, phase=gettext_noop("libvirt is still merging the snapshot"),
                           stalled=all(j["cur"] == j["end"] for j in jobs),
                           progress=_merged(jobs))
        if not listed:
            before = op.intent.get("before")  # recorded with effects_started; absent only if run never began
            left = proxy.left_behind_since(before) if before else []
            return Outcome(Operation.SUCCEEDED, result={"left_behind": left})
        return Outcome(Operation.UNCERTAIN,
                       error="The snapshot is still listed and no merge runs. It cannot be told whether the disks "
                             "changed; check the VM before deleting the snapshot again or reverting to it.")

    def log_entry(self, op, state):
        return _log(op, state, f"delete external snapshot {op.params['name']}")


GONE = "The VM is no longer on the compute the job ran on"


@register
class CreateSnapshot(Kind):
    name = "snapshot.create"
    label = gettext_noop("Take snapshot")
    time_limit = 6 * 3600  # a snapshot cannot be stopped: over time is only noted

    def normalize(self, raw):
        return {"instance": int(raw["instance"]), "name": str(raw.get("name", "")),
                "description": str(raw.get("description", "")), "external": bool(raw.get("external")),
                "memory": bool(raw.get("memory")), "quiesce": bool(raw.get("quiesce"))}

    def validate(self, user, params):
        check_snapshot_name(params["name"])
        # recovery counts a listed snapshot as taken by the job
        if params["name"] in _proxy(_authorized(user, params["instance"])).instance.snapshotListNames(0):
            raise util.OperationError(f"A snapshot named {params['name']} already exists")

    def plan(self, user, params):
        return _vm_plan(params)

    def precheck(self, op, ctx):
        _checked_proxy(op)

    def run(self, op, ctx):
        p = op.params
        proxy = _proxy(_instance(p["instance"]))
        ctx.record_intent()
        ctx.set_phase(gettext_noop("Taking the snapshot"))
        if p["external"]:
            proxy.create_external_snapshot(p["name"], p["description"], p["memory"], p["quiesce"],
                                           **_snapshot_free_space())
        else:
            proxy.create_snapshot(p["name"], p["description"])
        return {}

    def reconcile(self, op):
        proxy = _recovery_proxy(op)
        if proxy is None:
            return Outcome(Operation.UNCERTAIN, error=GONE)
        if _libvirt_busy(proxy.instance):
            return Outcome(Operation.RUNNING, phase=gettext_noop("libvirt is still taking the snapshot"))
        if op.params["name"] in proxy.instance.snapshotListNames(0):
            return Outcome(Operation.SUCCEEDED)
        return Outcome(Operation.FAILED, error="The snapshot was not taken")

    def log_entry(self, op, state):
        kind = "external snapshot" if op.params["external"] else "snapshot"
        return _log(op, state, f"take {kind} {op.params['name']}")


def _current(proxy):
    dom = proxy.instance
    return dom.snapshotCurrent(0).getName() if dom.hasCurrentSnapshot(0) else None


def _snapshot_definitions(proxy, params):
    """The VM's definitions in the snapshot a revert restores (as it runs,
    and as saved), and whether they give it host devices."""
    tree = etree.fromstring(proxy._snapshot(params["name"], params["external"]).getXMLDesc(0))
    definitions = tree.xpath("domain | inactiveDomain")
    return any(definition.xpath(HOST_DEVICES) for definition in definitions), definitions


@register
class RevertSnapshot(Kind):
    name = "snapshot.revert"
    label = gettext_noop("Revert snapshot")
    time_limit = 6 * 3600  # a revert cannot be stopped: over time is only noted

    def normalize(self, raw):
        return {"instance": int(raw["instance"]), "name": str(raw.get("name", "")),
                "external": bool(raw.get("external"))}

    def validate(self, user, params):
        _proxy(_authorized(user, params["instance"]))._snapshot(params["name"], params["external"])

    def plan(self, user, params):
        plan = _vm_plan(params)
        # a revert that gives the VM host devices holds the whole compute: no other VM takes them meanwhile
        if _snapshot_definitions(_proxy(_instance(params["instance"])), params)[0]:
            plan.claims[claims.compute_key(plan.intent["compute"])] = Claim.EXCLUSIVE
        return plan

    def precheck(self, op, ctx):
        proxy = _checked_proxy(op)
        if op.params["external"]:
            proxy.check_external_revert(op.params["name"])
        # a revert gives the VM the host devices it had then: not one given since to another VM
        has_hostdevs, definitions = _snapshot_definitions(proxy, op.params)
        if has_hostdevs:
            check_hostdevs(proxy, proxy.instance.name(), definitions)

    def run(self, op, ctx):
        proxy = _proxy(_instance(op.params["instance"]))
        ctx.record_intent(was_current=_current(proxy))
        ctx.set_phase(gettext_noop("Reverting the VM"))
        if op.params["external"]:
            return {"left_behind": proxy.revert_external_snapshot(op.params["name"])}
        proxy.snapshot_revert(op.params["name"])
        return {}

    def reconcile(self, op):
        proxy = _recovery_proxy(op)
        if proxy is None:
            return Outcome(Operation.UNCERTAIN, error=GONE)
        if _libvirt_busy(proxy.instance):
            return Outcome(Operation.RUNNING, phase=gettext_noop("libvirt is still reverting the VM"))
        if _current(proxy) == op.params["name"] != op.intent.get("was_current"):
            return Outcome(Operation.SUCCEEDED)
        return Outcome(Operation.UNCERTAIN, error="It cannot be told whether the VM was reverted; "
                                                  "check it, then revert again or resolve this job.")

    def log_entry(self, op, state):
        kind = "external snapshot" if op.params["external"] else "snapshot"
        return _log(op, state, f"revert to {kind} {op.params['name']}")


def _delete_created(proxy, op):
    """The volumes this job made; nothing else."""
    for entry in op.intent.get("created", []):
        try:
            proxy.get_volume_by_path(entry["path"]).delete(0)
        except libvirtError as err:
            if err.get_error_code() != VIR_ERR_NO_STORAGE_VOL:
                raise


CLONE_STATE_REFUSED = "The VM must be running, paused or shut off to be cloned"
THAW_FAILED = "The guest's file systems could not be thawed ({error}); thaw them with: virsh domfsthaw {vm}"


def _check_clone_state(proxy, data):
    """A shut-off VM is copied as it is; a running or paused one only when a
    live clone can work; other states are refused."""
    status = proxy.get_status()
    if status in (1, 3):
        proxy.live_clone_targets(data, **_snapshot_free_space())
    elif status != 5:
        raise util.OperationError(CLONE_STATE_REFUSED)


@register
class CloneInstance(Kind):
    """A shut-off VM is copied volume by volume; a running or paused one with
    libvirt's push backup, which copies its disks from one instant."""

    name = "instance.clone"
    label = gettext_noop("Clone VM")
    cancellable = True  # libvirt aborts a live copy; a shut-off copy runs to its end
    progress_bytes = True  # libvirt backup job disk_processed/disk_total

    def normalize(self, raw):
        fields = {k: str(v) for k, v in raw.items() if k in CLONE_FIELDS or CLONE_POST_KEY_RE.fullmatch(k)}
        return {"instance": int(raw["instance"]), "fields": fields}

    def plan(self, user, params):
        instance = _clonable(user, params["instance"])
        data = clone_data(user, instance, params["fields"])
        keys = vm_claims(instance.compute, data["name"])
        # the VM's definition is read again when the clone is defined
        keys[claims.instance_key(instance.uuid)] = Claim.EXCLUSIVE
        for disk in instance.config_disks:
            if name := data.get(f"disk-{disk['dev']}"):
                keys[claims.volume_key(instance.compute_id, disk["storage"], name)] = Claim.EXCLUSIVE
        _check_clone_state(instance.proxy, data)
        return Plan(claims=keys, resource=claims.instance_key(instance.uuid),
                    label=f"{instance.compute.name}/{instance.name}",
                    intent={"compute": instance.compute_id, "uuid": util.randomUUID(), "name": data["name"],
                            "clone": data})

    def precheck(self, op, ctx):
        instance = _clonable(op.user, op.params["instance"])
        if instance.compute_id != op.intent["compute"]:
            raise util.OperationError("The VM moved to another compute after the job was queued")
        _check_clone_state(instance.proxy, op.intent["clone"])

    def run(self, op, ctx):
        instance = _instance(op.params["instance"])
        proxy = instance.proxy
        clone, uuid = op.intent["clone"], op.intent["uuid"]
        status = proxy.get_status()
        if status == 5:
            ctx.record_intent(live=False)
            ctx.set_phase(gettext_noop("Copying disks"))
            proxy.clone_instance(clone, uuid)
            record_vm(op, owner=True)
            return {}
        if status not in (1, 3):
            raise util.OperationError(CLONE_STATE_REFUSED)
        targets = proxy.live_clone_targets(clone, **_snapshot_free_space())
        ctx.record_intent(live=True, targets=targets)
        ctx.set_phase(gettext_noop("Copying disks"))

        copies = []  # the targets at the paths libvirt gave their volumes
        for t in targets:
            ctx.record_intent(planned=[*op.intent.get("planned", []), {"dev": t["dev"], "path": t["path"]}])
            path = proxy.create_clone_target(t, clone["disk_owner_uid"], clone["disk_owner_gid"])
            ctx.record_intent(created=[*op.intent.get("created", []), {"dev": t["dev"], "path": path}])
            copies.append({**t, "path": path})

        # a completed result libvirt still holds is of an earlier job; after
        # copy_started, one can only be of this job's backup
        proxy.discard_backup_result()
        ctx.record_intent(copy_started=True)
        op.refresh_from_db(fields=["cancel_requested"])
        if op.cancel_requested:
            _delete_created(proxy, op)
            raise Cancelled

        freeze = status == 1 and proxy.is_agent_ready()
        warning = ""
        try:
            try:
                if freeze:
                    ctx.record_intent(frozen=True)
                    proxy.fs_freeze()
                proxy.begin_clone_backup(copies)
            finally:
                if freeze:
                    try:
                        proxy.fs_thaw()
                    except libvirtError as err:  # frozen stays recorded: recovery thaws again
                        warning = THAW_FAILED.format(error=err, vm=instance.name)
                    else:
                        ctx.record_intent(frozen=False)
        except libvirtError as err:
            # no backup of ours runs: the copy failed (if this read fails, recovery decides)
            if proxy.backup_targets() != {c["path"] for c in copies}:
                ctx.record_intent(copy_result=[False, str(err)])
            raise
        op.refresh_from_db(fields=["cancel_requested"])
        if op.cancel_requested:  # the cancel hook may have run before the backup began
            try:
                self.cancel(op)
            except libvirtError:
                pass  # the hook aborted it, or it ended: its result tells

        while proxy.backup_progress() is not None:
            time.sleep(2)
        result = proxy.backup_result()
        ctx.record_intent(copy_result=list(result) if result else None)
        if result is None:
            raise util.OperationError("libvirt has no result of the copy")  # recovery decides
        success, errmsg = result
        if success:
            proxy.define_clone(clone, uuid, {c["dev"]: c["path"] for c in copies})
            record_vm(op, owner=True)
            return {"warning": warning} if warning else {}
        _delete_created(proxy, op)
        op.refresh_from_db(fields=["cancel_requested"])
        if op.cancel_requested:
            raise Cancelled
        raise util.OperationError(" ".join(filter(None, [errmsg or "The copy failed", warning])))

    def progress(self, op):
        return _proxy(_instance(op.params["instance"])).backup_progress() if op.intent.get("live") else None

    def cancel(self, op):
        # a shut-off copy, or a live one not started yet (run checks the request first)
        if not op.intent.get("live"):
            return
        proxy = _proxy(_instance(op.params["instance"]))
        created = {c["path"] for c in op.intent.get("created", [])}
        if created and proxy.backup_targets() == created:
            proxy.abort_backup()

    def reconcile(self, op):
        if not op.intent.get("live"):
            disks = [v for k, v in op.intent["clone"].items() if k.startswith("disk-") and v]
            return vm_outcome(op, owner=True, volumes=disks)
        proxy = _recovery_proxy(op)
        if proxy is None:
            created = ", ".join(c["path"] for c in op.intent.get("created", []))
            return Outcome(Operation.UNCERTAIN, error=f"{GONE}; check these volumes, then resolve this job: {created}")
        warning = ""
        if op.intent.get("frozen") and proxy.get_status() == 1:
            try:
                proxy.fs_thaw()
            except libvirtError as err:
                warning = " " + THAW_FAILED.format(error=err, vm=op.resource_label.rpartition("/")[2])
        outcome = self._live_outcome(proxy, op)
        outcome.error += warning
        return outcome

    def _live_outcome(self, proxy, op):
        """The spec's recovery table: a defined clone first, then a volume
        still being created, since it comes before the copy."""
        if _domain(op.intent["compute"], op.intent["uuid"]) is not None:
            record_vm(op, owner=True)
            return Outcome(Operation.SUCCEEDED)
        created = op.intent.get("created", [])
        paths = [c["path"] for c in created]
        ended = Operation.CANCELLED if op.cancel_requested else Operation.FAILED
        done = {c["dev"] for c in created}
        planned = {p["dev"] for p in op.intent.get("planned", [])}
        for t in op.intent.get("targets", []):
            if t["dev"] not in planned or t["dev"] in done:
                continue
            try:
                proxy.wvm.storagePoolLookupByName(t["pool"]).storageVolLookupByName(t["name"])
            except libvirtError as err:
                if err.get_error_code() != VIR_ERR_NO_STORAGE_VOL:
                    raise
            else:
                paths.append(t["path"])
        check = f"check these volumes, then resolve this job: {', '.join(paths)}"
        if len(paths) > len(created):
            return Outcome(Operation.UNCERTAIN, error=f"A volume of the clone was being created; {check}")
        if not op.intent.get("copy_started"):
            _delete_created(proxy, op)
            return Outcome(ended, error="The job stopped before the copy started")
        # recorded only once this job's backup ended or never started
        result = op.intent.get("copy_result")
        if result is None:
            targets = proxy.backup_targets()
            if targets is not None:
                if targets == set(paths):
                    return Outcome(Operation.RUNNING, phase=gettext_noop("libvirt is still copying the disks"),
                                   progress=proxy.backup_progress())
                return Outcome(Operation.UNCERTAIN, error=f"Another backup runs on the VM; {check}")
            result = proxy.backup_result()
        if result is None:
            return Outcome(Operation.UNCERTAIN, error=f"libvirt has no result of the copy; {check}")
        success, errmsg = result
        if not success:
            _delete_created(proxy, op)
            return Outcome(ended, error=errmsg or "The copy failed")
        proxy.define_clone(op.intent["clone"], op.intent["uuid"], {c["dev"]: c["path"] for c in created})
        record_vm(op, owner=True)
        return Outcome(Operation.SUCCEEDED)

    def log_entry(self, op, state):
        source = op.resource_label.rpartition("/")[2]
        return _log(op, state, f"clone from {source}", vm=op.intent["name"])


# pools whose volumes are files a CD-ROM can read
SEED_POOL_TYPES = ("dir", "fs", "netfs")


def _seed_pool(conn, data):
    """The pool of a new VM's cloud-init seed: the one of its disk."""
    if data["storage"]:
        return conn.get_storage(data["storage"])
    return conn.get_storage_by_vol_path(conn.get_volume_path(data["images"].split(",")[0]))


@register
class CreateInstance(Kind):
    name = "instance.create"
    label = gettext_noop("Create VM")
    time_limit = 12 * 3600  # a copy cannot be stopped: over time is only noted

    def normalize(self, raw):
        # what the API leaves out means what create_instance did by default
        params = {"template": "", "images": "", "firmware": "", "net_model": "virtio", "add_cdrom": "sata",
                  "add_input": "default", "meta_prealloc": False, "hdd_size": 0, "cloud_init": False}
        params.update({k: v for k, v in raw.items() if k not in ("submission_key", "create", "csrfmiddlewaretoken")})
        params.update(compute=int(raw["compute"]), devices=[list(d) for d in raw.get("devices", [])])
        if "UEFI" in params["firmware"] and "secboot" in params["firmware"].partition(":")[2]:
            params["machine"] = "q35"  # a secure boot loader needs SMM, on q35 only
        return params

    def validate(self, user, params):
        from instances.views import CDROM_BUSES

        if not user.is_superuser:
            raise PermissionDenied
        data = params
        c = get_object_or_404(Compute, pk=data["compute"])
        conn = wvmCreate(c.hostname, c.login, c.password, c.type)
        cdrom_buses = [bus for bus in conn.get_disk_bus_types(data["arch"], data["machine"]) if bus in CDROM_BUSES]
        if data["name"] in conn.get_instances():
            raise util.OperationError(_("A virtual machine with this name already exists"))
        if Instance.objects.filter(name__exact=data["name"]):
            raise util.OperationError(_("There is an instance with same name. Remove it and try again!"))
        sources = [source for source in ("hdd_size", "template", "images") if data[source]]
        if not sources:
            raise util.OperationError(_("First you need to create or select an image"))
        if len(sources) > 1:
            raise util.OperationError(_("Choose one disk source: a new disk, existing volumes or a template"))
        if not data["hdd_size"] and data["template"] and conn.get_volume_path(data["name"] + ".img", data["storage"]):
            raise util.OperationError(_("Image has already exist. Please check volumes or change instance name"))
        if data["cache_mode"] not in conn.get_cache_modes():
            raise util.OperationError(_("Invalid cache mode"))
        if data["vcpu_mode"] not in cpu_choices(conn.get_dom_capabilities(data["arch"], data["machine"])):
            raise util.OperationError(_("This host offers no CPU mode or model %(mode)s") % {"mode": data["vcpu_mode"]})
        if data["add_cdrom"] != "None" and data["add_cdrom"] not in cdrom_buses:
            raise util.OperationError(_("A CD-ROM cannot use the %(bus)s bus") % {"bus": data["add_cdrom"]})
        if data["cloud_init"]:
            if data["add_cdrom"] == "None":
                raise util.OperationError(_("The cloud-init seed is read from a CD-ROM: choose its bus"))
            pool = _seed_pool(conn, data)
            if util.get_xml_path(pool.XMLDesc(0), "/pool/@type") not in SEED_POOL_TYPES:
                raise util.OperationError(_("The cloud-init seed needs a directory storage pool for the disk"))
        try:
            utils.nic_macs(data["mac"], data["networks"])
        except ValueError as err:
            raise util.OperationError(str(err))
        if "UEFI" in data["firmware"] and ":" not in data["firmware"]:
            raise util.OperationError(_("Invalid firmware"))

    def plan(self, user, params):
        compute = Compute.objects.get(pk=params["compute"])
        return Plan(claims=vm_claims(compute, params["name"]), resource=claims.compute_key(compute.pk),
                    label=f"{compute.name}/{params['name']}",
                    intent={"compute": compute.pk, "uuid": util.randomUUID(), "name": params["name"]})

    def run(self, op, ctx):
        data = op.params
        c = Compute.objects.get(pk=data["compute"])
        conn = wvmCreate(c.hostname, c.login, c.password, c.type)
        meta_prealloc = bool(data["meta_prealloc"])
        default_bus = app_settings.INSTANCE_VOLUME_DEFAULT_BUS
        default_disk_format = app_settings.INSTANCE_VOLUME_DEFAULT_FORMAT
        default_disk_owner_uid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
        default_disk_owner_gid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)

        firmware = dict()
        if "UEFI" in data["firmware"]:
            firmware["loader"] = data["firmware"].split(":")[1].strip()
            firmware["secure"] = "yes" if "secboot" in firmware["loader"] else "no"
            firmware["readonly"] = "yes"
            firmware["type"] = "pflash"

        def volume(path, device="disk", bus=default_bus):
            return {
                "path": path,
                "type": conn.get_volume_format_type(path),
                "device": device,
                "bus": bus,
                "scsi_model": app_settings.INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER if bus == "scsi" else None,
                "cache_mode": data["cache_mode"],
                "discard_mode": app_settings.INSTANCE_VOLUME_DEFAULT_DISCARD,
                "detect_zeroes_mode": app_settings.INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES,
                "io_mode": app_settings.INSTANCE_VOLUME_DEFAULT_IO,
            }

        ctx.record_intent()
        ctx.set_phase(gettext_noop("Copying disks"))
        created = []  # volumes this job allocated
        volume_list = []
        try:
            if data["hdd_size"]:
                path = conn.create_volume(data["storage"], data["name"], data["hdd_size"], default_disk_format,
                                          meta_prealloc, default_disk_owner_uid, default_disk_owner_gid)
                created.append(path)
                volume_list.append(volume(path))
            elif data["template"]:
                path = conn.clone_from_template(data["name"], conn.get_volume_path(data["template"]), data["storage"],
                                                meta_prealloc, default_disk_owner_uid, default_disk_owner_gid)
                created.append(path)
                volume_list.append(volume(path))
            else:
                for vol, (device, bus) in zip(data["images"].split(","), data["devices"]):
                    volume_list.append(volume(conn.get_volume_path(vol), device, bus))

            if data["cloud_init"]:
                ctx.set_phase(gettext_noop("Writing the cloud-init seed"))
                keys = UserSSHKey.objects.filter(user=op.user).values_list("keypublic", flat=True)
                user_data = render_to_string("user_data", {"instance_keys": list(keys)})
                seed = conn.create_seed(_seed_pool(conn, data).name(), op.intent["uuid"], data["name"], user_data)
                created.append(seed)
                volume_list.append(volume(seed, "cdrom", data["add_cdrom"]))

            ctx.set_phase(gettext_noop("Defining the VM"))
            conn.create_instance(
                name=data["name"],
                memory=data["memory"],
                vcpu=data["vcpu"],
                vcpu_mode=data["vcpu_mode"],
                uuid=op.intent["uuid"],
                arch=data["arch"],
                machine=data["machine"],
                firmware=firmware,
                volumes=volume_list,
                networks=data["networks"],
                virtio=data["virtio"],
                listener_addr=data["listener_addr"],
                nwfilter=data["nwfilter"],
                net_model="virtio" if data["net_model"] == "default" else data["net_model"],
                video=data["video"],
                console_pass="",
                mac=data["mac"],
                qemu_ga=data["qemu_ga"],
                add_cdrom=data["add_cdrom"],
                add_input=data["add_input"],
            )
        except Exception as err:
            # the VM is not defined: its new volumes go
            leftovers = []
            for path in created:
                try:
                    conn.delete_volume(path)
                except libvirtError:
                    leftovers.append(path)
            if leftovers:
                raise util.OperationError(f"{err}. Remove these volumes by hand: {', '.join(leftovers)}") from err
            raise
        record_vm(op, owner=False)
        return {}

    def reconcile(self, op):
        data = op.params
        names = [data["name"] + ext for ext in ("", ".img", ".qcow", ".qcow2")] if data["hdd_size"] or data["template"] else []
        if data.get("cloud_init"):
            names.append(f"cidata-{op.intent['uuid']}.iso")
        return vm_outcome(op, owner=False, volumes=names)

    def log_entry(self, op, state):
        return _log(op, state, "create")


MIGRATE_OPTIONS = ("live", "unsafe", "offline", "autoconverge", "compress", "delete_source")


def _target(instance, target_pk):
    """The destination; refused when the VM is already there or it cannot be reached."""
    target = Compute.objects.get(pk=target_pk)
    if target.pk == instance.compute_id:
        raise util.OperationError(_("The instance is already on %(compute)s") % {"compute": target.name})
    if not target.status:
        raise util.OperationError(_("%(compute)s is not reachable") % {"compute": target.name})
    return target


def _domain(compute_pk, uuid):
    """The VM on the compute, or None when it has none there."""
    c = Compute.objects.get(pk=compute_pk)
    try:
        return wvmConnect(c.hostname, c.login, c.password, c.type).wvm.lookupByUUIDString(uuid)
    except libvirtError as err:
        if err.get_error_code() != VIR_ERR_NO_DOMAIN:
            raise  # unreachable: recovery waits and retries
        return None


@register
class MigrateInstance(Kind):
    name = "instance.migrate"
    label = gettext_noop("Migrate VM")
    cancellable = True  # libvirt aborts a migration; the VM keeps running on the source
    progress_bytes = True  # libvirt job data processed/total

    def normalize(self, raw):
        # disk_pools: {target: pool of the destination} of the disks to copy there
        return {"instance": int(raw["instance"]), "target": int(raw["target"]),
                "disk_pools": {str(k): str(v) for k, v in (raw.get("disk_pools") or {}).items() if v},
                **{k: bool(raw.get(k)) for k in MIGRATE_OPTIONS}}

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied
        _target(_instance(params["instance"]), params["target"])

    def plan(self, user, params):
        instance = _instance(params["instance"])
        keys = vm_claims(Compute.objects.get(pk=params["target"]), instance.name)
        keys.update({claims.compute_key(instance.compute_id): Claim.SHARED,
                     claims.reconcile_key(instance.compute_id): Claim.EXCLUSIVE,
                     claims.instance_key(instance.uuid): Claim.EXCLUSIVE})
        if params["disk_pools"]:
            # a copy takes its file's name in the chosen pool; the source file may go
            for disk in instance.proxy.get_disk_devices():
                if pool := params["disk_pools"].get(disk["dev"]):
                    keys[claims.volume_key(params["target"], pool, os.path.basename(disk["path"]))] = Claim.EXCLUSIVE
                    if disk["storage"]:
                        keys[claims.volume_key(instance.compute_id, disk["storage"], disk["image"])] = Claim.EXCLUSIVE
        return Plan(claims=keys, resource=claims.instance_key(instance.uuid),
                    label=f"{instance.compute.name}/{instance.name}",
                    intent={"compute": instance.compute_id, "uuid": instance.uuid})

    def precheck(self, op, ctx):
        if op.user is None or not op.user.is_active or not op.user.is_superuser:
            raise PermissionDenied
        instance = _instance(op.params["instance"])
        if instance.compute_id != op.intent["compute"]:
            raise util.OperationError("The VM moved to another compute after the job was queued")
        _target(instance, op.params["target"])

    def run(self, op, ctx):
        p = op.params
        instance = _instance(p["instance"])
        ctx.record_intent()
        ctx.set_phase(gettext_noop("Migrating the VM"))
        try:
            # migrate_instance logs the outcome
            utils.migrate_instance(Compute.objects.get(pk=p["target"]), instance, op.user,
                                   disk_pools=p["disk_pools"],
                                   **{k: p[k] for k in MIGRATE_OPTIONS})
        except libvirtError:
            op.refresh_from_db(fields=["cancel_requested"])
            if op.cancel_requested:
                raise Cancelled from None
            raise
        return {}

    def progress(self, op):
        info = _proxy(_instance(op.params["instance"])).instance.jobInfo()
        return (info[4], info[3]) if info[3] else None

    def cancel(self, op):
        dom = _proxy(_instance(op.params["instance"])).instance
        # the worker sends a cancel once: one that comes before libvirt began
        # the migration waits for it, or for the job to end without it
        while not _libvirt_busy(dom):
            if not Operation.objects.filter(pk=op.pk, state__in=Operation.ACTIVE).exists():
                return
            time.sleep(1)
        # an error (the migration ended meanwhile) goes to the worker log
        dom.abortJob()

    def reconcile(self, op):
        source = _domain(op.intent["compute"], op.intent["uuid"])
        dest = _domain(op.params["target"], op.intent["uuid"])
        if source is not None and _libvirt_busy(source):
            return Outcome(Operation.RUNNING, phase=gettext_noop("libvirt is still migrating the VM"))
        if source is None and dest is not None:
            instance = Instance.objects.filter(pk=op.params["instance"], compute_id=op.intent["compute"]).first()
            if instance is not None:  # the job stopped before it moved the record
                utils.record_migration(instance, Compute.objects.get(pk=op.params["target"]))
            return Outcome(Operation.SUCCEEDED)
        if source is not None and dest is None:
            return Outcome(Operation.FAILED, error="The VM stayed on the source host")
        return Outcome(Operation.UNCERTAIN, error="The VM is on both computes or on neither; "
                                                  "check them, then resolve this job.")


DISK_DEV = re.compile(r"[a-z][a-z0-9]*")


def _movable(user, params):
    """The disk move's VM, for a superuser, and its plan (disk_move_plan)."""
    if user is None or not user.is_active or not user.is_superuser:
        raise PermissionDenied
    instance = _instance(params["instance"])
    return instance, _proxy(instance).disk_move_plan(params["dev"], params["pool"])


def _used_anywhere(path):
    """Whether a VM or volume of any compute uses path (paths_in_use), as
    shared storage holds it for every host that mounts it; a compute that
    cannot be read might."""
    for c in Compute.objects.all():
        try:
            if path in wvmConnect(c.hostname, c.login, c.password, c.type).paths_in_use():
                return True
        except libvirtError:
            return True
    return False


@register
class MoveDisk(Kind):
    """A disk of a VM to another storage pool of its host (disk_move_plan)."""

    name = "disk.move"
    label = gettext_noop("Move disk")
    cancellable = True  # a block copy is aborted; a shut-off VM's volume copy runs to its end
    progress_bytes = True  # libvirt block job cur/end

    def normalize(self, raw):
        dev = str(raw.get("dev", ""))
        if not DISK_DEV.fullmatch(dev):
            raise util.OperationError("Choose a disk of the VM")
        return {"instance": int(raw["instance"]), "dev": dev, "pool": str(raw.get("pool", ""))}

    def validate(self, user, params):
        _movable(user, params)

    def plan(self, user, params):
        instance, move = _movable(user, params)
        plan = _vm_plan(params)
        source_pool = move["volume"].storagePoolLookupByVolume().name()
        name = os.path.basename(move["path"])
        for pool in (source_pool, params["pool"]):
            plan.claims[claims.volume_key(instance.compute_id, pool, name)] = Claim.EXCLUSIVE
        return plan

    def precheck(self, op, ctx):
        instance, _move = _movable(op.user, op.params)
        if instance.compute_id != op.intent["compute"]:
            raise util.OperationError("The VM moved to another compute after the job was queued")

    def run(self, op, ctx):
        instance, move = _movable(op.user, op.params)
        proxy = _proxy(instance)
        ctx.record_intent(path=move["path"], dest=move["dest"])
        ctx.set_phase(gettext_noop("Copying the disk"))
        try:
            proxy.move_disk(move)
        except libvirtError:
            op.refresh_from_db(fields=["cancel_requested"])
            # cancelled only when the copy stopped and the VM kept its file
            if op.cancel_requested and proxy.disk_named(move["dev"]) == {move["path"]} \
                    and not (move["running"] and proxy.instance.blockJobInfo(move["dev"], 0)):
                raise Cancelled from None
            raise
        # the move stands: a source file that cannot go is only left behind
        try:
            if not _used_anywhere(move["path"]):
                move["volume"].delete(0)
                return {"left_behind": []}
        except libvirtError:
            pass
        return {"left_behind": [move["path"]]}

    def progress(self, op):
        info = _proxy(_instance(op.params["instance"])).instance.blockJobInfo(op.params["dev"], 0)
        return (info["cur"], info["end"]) if info else None

    def cancel(self, op):
        dom = _proxy(_instance(op.params["instance"])).instance
        # the worker sends a cancel once: one before the copy began waits for it
        while dom.isActive() and not dom.blockJobInfo(op.params["dev"], 0):
            if not Operation.objects.filter(pk=op.pk, state__in=Operation.ACTIVE).exists():
                return
            time.sleep(1)
        if dom.isActive():
            dom.blockJobAbort(op.params["dev"], 0)

    def reconcile(self, op):
        proxy = _recovery_proxy(op)
        if proxy is None:
            return Outcome(Operation.UNCERTAIN, error=GONE)
        dev, path, dest = op.params["dev"], op.intent.get("path"), op.intent.get("dest")
        dom = proxy.instance
        # a copy no worker waits for mirrors forever: it ends here
        if dest and dom.isActive() and dom.blockJobInfo(dev, 0):
            mirror = etree.fromstring(dom.XMLDesc(0)).xpath(f"devices/disk[target/@dev='{dev}']/mirror/source/@file")
            if mirror != [dest]:
                return Outcome(Operation.UNCERTAIN, error=f"Another block job runs on {dev}; check the VM")
            dom.blockJobAbort(dev, 0)
        named = proxy.disk_named(dev)
        if named == {dest}:
            return Outcome(Operation.SUCCEEDED, result={"left_behind": [path]})
        if named == {path}:
            return Outcome(Operation.FAILED, error=f"The disk stayed in {path}; remove {dest} if it is there")
        return Outcome(Operation.UNCERTAIN, error=f"The definitions of {dev} name {', '.join(sorted(map(str, named)))}; "
                                                  "check the VM")

    def log_entry(self, op, state):
        return _log(op, state, f"move disk {op.params['dev']} to pool {op.params['pool']}")
