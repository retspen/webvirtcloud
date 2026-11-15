"""Jobs of the computes app (operations framework)."""

import time
from contextlib import suppress

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_noop
from instances.models import Instance
from vrtManager import util

from computes.models import Compute
from operations import claims, jobs, utils
from operations.jobs import Cancelled, Kind, Outcome, Plan, register
from operations.models import Claim, Operation


# where a host is: a bulk migration stops if either host's record points elsewhere since it was asked
WHERE = ("hostname", "login", "type")


def _where(params):
    return [list(Compute.objects.filter(pk=pk).values_list(*WHERE).first() or []) for pk in (params["compute"], params["target"])]


def parallel_limit():
    """The most migrations a bulk migration runs at once: the worker gives a
    host's jobs half of its slots, and the bulk migration itself takes one."""
    slots = utils.concurrency()
    return min(max(1, slots // 2), slots - 1)


@register
class BulkMigrate(Kind):
    """Migrates the chosen VMs of a host to another, each in a migrate job
    of its own, at most parallel at once: one that fails leaves its VM on
    the host and the rest go on."""

    name = "host.bulk_migrate"
    label = gettext_noop("Bulk migrate")
    cancellable = True

    def normalize(self, raw):
        return {"compute": int(raw["compute"]), "target": int(raw["target"]), "parallel": int(raw["parallel"]),
                "instances": sorted({int(pk) for pk in raw["instances"]})}

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied
        if not params["instances"]:
            raise util.OperationError(gettext_noop("Choose the VMs to migrate"))
        if not 1 <= params["parallel"] <= parallel_limit():
            raise util.OperationError(gettext_noop("At most %(limit)s migrations can run at once"),
                                      limit=parallel_limit())

    def plan(self, user, params):
        compute = Compute.objects.get(pk=params["compute"])
        target = Compute.objects.get(pk=params["target"])
        return Plan(claims={claims.bulk_migrate_key(): Claim.EXCLUSIVE}, resource=claims.compute_key(compute.pk),
                    label=f"{compute.name} -> {target.name}", intent={"migrations": {}, "where": _where(params)})

    def precheck(self, op, ctx):
        if op.user is None or not op.user.is_active or not op.user.is_superuser:
            raise PermissionDenied

    def run(self, op, ctx):
        p = op.params
        names = dict(Instance.objects.filter(pk__in=p["instances"], compute_id=p["compute"]).values_list("pk", "name"))
        waiting = [pk for pk in p["instances"] if pk in names]  # one moved or deleted meanwhile is left out
        started, refused = {}, []  # VM: its migrate job; the VMs whose job was refused, and why
        ctx.record_intent()
        ctx.set_phase(gettext_noop("Migrating the VMs"))

        def stop(text, **values):
            """End the job failed; recovery, which the worker hands such a job, adds nothing."""
            ctx.record_intent(stopped=True)
            raise util.OperationError(text, **values)

        while True:
            running = list(Operation.objects.filter(pk__in=started.values(), state__in=Operation.ACTIVE)
                           .values_list("pk", flat=True))
            op.refresh_from_db(fields=["cancel_requested"])
            if op.cancel_requested:
                for pk in running:
                    with suppress(Exception):  # it ended meanwhile
                        jobs.cancel(pk, op.user)
                raise Cancelled
            # the worker's slots may have been lowered: this job waits in one, its migrations need others;
            # once it ends, the migrations it queued run
            if parallel_limit() < 1:
                stop(gettext_noop("The worker now runs one job at a time: the VMs not yet started stay on the host"))
            if waiting and _where(p) != op.intent["where"]:
                stop(gettext_noop("A host was changed or deleted: the VMs not yet started stay on the host"))
            for pk in list(waiting):
                if len(running) >= min(p["parallel"], parallel_limit()):
                    break
                waiting.remove(pk)
                if not Instance.objects.filter(pk=pk, compute_id=p["compute"]).exists():
                    continue  # it left the host meanwhile
                raw = {"instance": pk, "source": p["compute"], "target": p["target"], "live": True, "autoconverge": True}
                try:
                    child = jobs.submit("instance.migrate", op.user, raw, f"bulk-{op.pk.hex}-{pk}", parent=op)
                except claims.Busy as busy:
                    if busy.blocker is not None and busy.blocker.state == Operation.UNCERTAIN:
                        # it holds its claims until someone resolves it
                        refused.append(f"{names[pk]}: {utils.busy_message(busy, op.user)}")
                    else:
                        waiting.append(pk)  # another job holds the VM or a host: asked again on the next round
                except Exception as err:
                    refused.append(f"{names[pk]}: {utils.safe_text(err)}")
                else:
                    started[pk] = child.pk
                    running.append(child.pk)
                    ctx.record_intent(migrations={str(vm): str(job) for vm, job in started.items()})
            if not waiting and not running:
                break
            time.sleep(2)
        migrated = set(Operation.objects.filter(pk__in=started.values(), state=Operation.SUCCEEDED)
                       .values_list("pk", flat=True))
        failed = refused + [names[vm] for vm, job in started.items() if job not in migrated]
        if failed:
            stop(gettext_noop("These VMs did not migrate: %(vms)s"), vms=", ".join(failed))
        return {}

    def progress(self, op):
        """(the VMs whose migration ended, the chosen VMs)."""
        return op.children.filter(state__in=Operation.TERMINAL).count(), len(op.params["instances"])

    def cancel(self, op):
        """run sees the cancel and cancels the migrations that run."""

    def reconcile(self, op):
        if op.intent.get("stopped"):
            return Outcome(Operation.FAILED)  # its own error says why
        return Outcome(Operation.FAILED, error=utils.say(gettext_noop(
            "The bulk migration stopped: the migrations it started go on as their own jobs; the other VMs stay")))

    def log_entry(self, op, state):
        source, _sep, target = op.resource_label.partition(" -> ")
        message = f"Bulk migrate to {target}"
        return source, "", "", message if state == Operation.SUCCEEDED else f"{message} ({state})"
