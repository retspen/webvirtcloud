"""Jobs of the storages app (operations framework)."""

import logging
import os

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_noop
from vrtManager import util
from vrtManager.storage import wvmStorage

from computes.models import Compute
from operations import claims, utils
from operations.jobs import Kind, Outcome, Plan, register
from operations.models import Claim, Operation

from storages import upload

logger = logging.getLogger(__name__)


def _log(op, state, action):
    compute, _sep, pool = op.resource_label.rpartition("/")  # a pool name has no "/"
    message = f"Storage pool {pool}: {action}"
    return compute, "", "", message if state == Operation.SUCCEEDED else f"{message} ({state})"


def _storage(params):
    c = Compute.objects.get(pk=params["compute"])
    return c, wvmStorage(c.hostname, c.login, c.password, c.type, params["pool"])


@register
class CloneVolume(Kind):
    name = "volume.clone"
    label = gettext_noop("Clone volume")
    time_limit = 12 * 3600  # a copy cannot be stopped: over time is only noted

    def normalize(self, raw):
        fmt = str(raw.get("format") or "") if raw.get("convert") else ""
        return {"compute": int(raw["compute"]), "pool": str(raw["pool"]), "image": str(raw["image"]),
                "name": str(raw["name"]), "format": fmt, "prealloc": fmt == "qcow2" and bool(raw.get("meta_prealloc"))}

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied

    def plan(self, user, params):
        compute, stg = _storage(params)
        volumes = stg.get_volumes()
        if params["image"] not in volumes:
            raise util.OperationError(f"The pool has no volume named {params['image']}")
        target = stg.clone_name(params["name"], params["format"] or stg.get_volume_format_type(params["image"]))
        if target in volumes:
            raise util.OperationError("Name of volume already in use")
        pool = claims.pool_key(compute.pk, params["pool"])
        return Plan(claims={claims.compute_key(compute.pk): Claim.SHARED, pool: Claim.SHARED,
                            claims.volume_key(compute.pk, params["pool"], target): Claim.EXCLUSIVE},
                    resource=pool, label=f"{compute.name}/{params['pool']}", intent={"target": target})

    def run(self, op, ctx):
        _compute, stg = _storage(op.params)
        ctx.record_intent()
        ctx.set_phase(gettext_noop("Copying the volume"))
        created = stg.clone_volume(op.params["image"], op.params["name"], op.params["format"] or None,
                                   op.params["prealloc"])
        ctx.record_intent(created=created)
        return {}

    def reconcile(self, op):
        if op.intent.get("created"):
            return Outcome(Operation.SUCCEEDED)
        _compute, stg = _storage(op.params)  # unreachable: recovery waits and retries
        if op.intent["target"] in stg.get_volumes():
            return Outcome(Operation.UNCERTAIN, error="The copy exists, but the job did not see it finish; "
                                                      "check it, then resolve this job.")
        return Outcome(Operation.FAILED, error="The copy was not made")

    def log_entry(self, op, state):
        return _log(op, state, f"clone volume {op.params['image']} as {op.intent['target']}")


@register
class UploadVolume(Kind):
    """An ISO upload: its chunk requests run it (storages.upload)."""

    name = "volume.upload"
    label = gettext_noop("Upload ISO image")
    cancellable = True
    progress_bytes = True
    runs_in_request = True

    def normalize(self, raw):
        return {"compute": int(raw["compute"]), "pool": str(raw["pool"]),
                "name": os.path.basename(str(raw["name"])).strip(), "size": int(raw["size"]),
                "chunks": int(raw["chunks"])}

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied
        name = params["name"]
        if not name or name in (".", "..") or "\x00" in name:
            raise ValueError("Invalid file name")
        if len(name) <= 4 or not name.lower().endswith(".iso"):
            raise ValueError("Only .iso files can be uploaded")
        if params["size"] <= 0:
            raise ValueError("Invalid file size")
        if params["chunks"] < 1:
            raise ValueError("Invalid chunk index or total chunks")

    def plan(self, user, params):
        compute, stg = _storage(params)
        stg.refresh()
        if params["name"] in stg.get_volumes():
            raise FileExistsError(f"The pool has a volume named {params['name']}")
        pool = claims.pool_key(compute.pk, params["pool"])
        return Plan(claims={claims.compute_key(compute.pk): Claim.SHARED, pool: Claim.SHARED,
                            claims.volume_key(compute.pk, params["pool"], params["name"]): Claim.EXCLUSIVE},
                    resource=pool, label=f"{compute.name}/{params['pool']}", intent={"chunk": 0, "created": False})

    def cancel(self, op):
        try:
            upload.end(op, Operation.CANCELLED)
        except Exception as err:  # the next chunk or the expiry ends it
            logger.error("cancelling upload %s failed: %s", op.pk, utils.safe_text(err))

    def expire(self, op):
        upload.end(op, Operation.FAILED, upload.IDLE)

    def log_entry(self, op, state):
        return _log(op, state, f"upload volume {op.params['name']}")
