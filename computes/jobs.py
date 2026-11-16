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


# where a host is: a bulk migration stops if a host's record points elsewhere since it was asked
WHERE = ("hostname", "login", "type")


def _where(hosts):
    return [list(Compute.objects.filter(pk=pk).values_list(*WHERE).first() or []) for pk in sorted(hosts)]


def parallel_limit():
    """The most migrations a bulk migration runs at once: the worker gives a
    host's jobs half of its slots, and the bulk migration itself takes one."""
    slots = utils.concurrency()
    return min(max(1, slots // 2), slots - 1)


class Migrations(Kind):
    """Migrates VMs, each in a migrate job of its own, at most parallel at
    once: one that fails stays where it is and the rest go on. One such job
    at a time (it waits in a worker slot for its migrations). A kind gives
    its moves, [(VM, source, target)], and the options of its migrations."""

    cancellable = True
    options = {}

    def moves(self, params):
        raise NotImplementedError

    def hosts(self, params):
        return {host for _vm, source, target in self.moves(params) for host in (source, target)}

    def check_move(self, source, target):
        """Refuses (OperationError) a move to a host in maintenance, when the
        job is asked for and again before the VM's migration starts; the
        migrate job checks the rest."""
        if host := Compute.objects.filter(pk=target).first():
            host.refuse_new_vms()

    def validate(self, user, params):
        if not user.is_superuser:
            raise PermissionDenied
        if not self.moves(params):
            raise util.OperationError(gettext_noop("Choose the VMs to migrate"))
        if not 1 <= params["parallel"] <= parallel_limit():
            raise util.OperationError(gettext_noop("At most %(limit)s migrations can run at once"),
                                      limit=parallel_limit())
        for _vm, source, target in self.moves(params):
            self.check_move(source, target)

    def precheck(self, op, ctx):
        if op.user is None or not op.user.is_active or not op.user.is_superuser:
            raise PermissionDenied

    def run(self, op, ctx):
        p = op.params
        moves = self.moves(p)
        names = dict(Instance.objects.filter(pk__in=[vm for vm, _source, _target in moves]).values_list("pk", "name"))
        waiting = [move for move in moves if move[0] in names]  # one deleted meanwhile is left out
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
                stop(gettext_noop("The worker now runs one job at a time: the VMs not yet started stay where they are"))
            if waiting and _where(self.hosts(p)) != op.intent["where"]:
                stop(gettext_noop("A host was changed or deleted: the VMs not yet started stay where they are"))
            for move in list(waiting):
                if len(running) >= min(p["parallel"], parallel_limit()):
                    break
                waiting.remove(move)
                vm, source, target = move
                if not Instance.objects.filter(pk=vm, compute_id=source).exists():
                    continue  # it left its host meanwhile
                raw = {"instance": vm, "source": source, "target": target, "live": True, "autoconverge": True,
                       **self.options}
                try:
                    self.check_move(source, target)  # a host put in maintenance since
                    child = jobs.submit("instance.migrate", op.user, raw, f"bulk-{op.pk.hex}-{vm}", parent=op)
                except claims.Busy as busy:
                    if busy.blocker is not None and busy.blocker.state == Operation.UNCERTAIN:
                        # it holds its claims until someone resolves it
                        refused.append(f"{names[vm]}: {utils.busy_message(busy, op.user)}")
                    else:
                        waiting.append(move)  # another job holds the VM or a host: asked again on the next round
                except Exception as err:
                    refused.append(f"{names[vm]}: {utils.safe_text(err)}")
                else:
                    started[vm] = child.pk
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
        """(the VMs whose migration ended, the VMs to migrate)."""
        return op.children.filter(state__in=Operation.TERMINAL).count(), len(self.moves(op.params))

    def cancel(self, op):
        """run sees the cancel and cancels the migrations that run."""

    def reconcile(self, op):
        if op.intent.get("stopped"):
            return Outcome(Operation.FAILED)  # its own error says why
        return Outcome(Operation.FAILED, error=utils.say(gettext_noop(
            "The bulk migration stopped: the migrations it started go on as their own jobs; the other VMs stay")))


@register
class BulkMigrate(Migrations):
    """Migrates the chosen VMs of a host to other hosts, one or several,
    for the host's maintenance: a running VM live, a shut-off one offline."""

    name = "host.bulk_migrate"
    label = gettext_noop("Bulk migrate")

    def normalize(self, raw):
        moves = {int(vm): int(target) for vm, target in raw["moves"]}
        # maintenance: the host was put in maintenance with the job (computes.views.bulk_migrate)
        return {"compute": int(raw["compute"]), "parallel": int(raw["parallel"]),
                "moves": [[vm, target] for vm, target in sorted(moves.items())],
                "maintenance": bool(raw.get("maintenance"))}

    def moves(self, params):
        return [(vm, params["compute"], target) for vm, target in params["moves"]]

    def validate(self, user, params):
        super().validate(user, params)
        targets = {target for _vm, target in params["moves"]}
        if params["compute"] in targets:
            raise util.OperationError(gettext_noop("A VM is already on its destination"))
        if Compute.objects.filter(pk__in=targets).count() != len(targets):
            raise util.OperationError(gettext_noop("A destination host was deleted"))

    def plan(self, user, params):
        compute = Compute.objects.get(pk=params["compute"])
        targets = {target for _vm, target in params["moves"]}
        names = Compute.objects.filter(pk__in=targets).order_by("name").values_list("name", flat=True)
        return Plan(claims={claims.bulk_migrate_key(): Claim.EXCLUSIVE}, resource=claims.compute_key(compute.pk),
                    label=f"{compute.name} -> {', '.join(names)}",
                    intent={"migrations": {}, "where": _where(self.hosts(params))})

    def log_entry(self, op, state):
        source, _sep, targets = op.resource_label.partition(" -> ")
        message = f"Bulk migrate to {targets}"
        return source, "", "", message if state == Operation.SUCCEEDED else f"{message} ({state})"


@register
class Balance(Migrations):
    """Migrates running VMs between hosts, as the Balance page proposed, to
    even out what the hosts give their running VMs. Each migration takes
    only a running VM: one stopped since is left where it is."""

    name = "host.balance"
    label = gettext_noop("Balance")
    options = {"running_only": True}

    def normalize(self, raw):
        moves = {int(vm): (int(source), int(target)) for vm, source, target in raw["moves"]}
        return {"parallel": int(raw["parallel"]),
                "moves": [[vm, source, target] for vm, (source, target) in sorted(moves.items())]}

    def moves(self, params):
        return [tuple(move) for move in params["moves"]]

    def check_move(self, source, target):
        """Balance leaves a host in maintenance out: it takes no VM and gives none."""
        super().check_move(source, target)
        if host := Compute.objects.filter(pk=source, maintenance=True).first():
            raise util.OperationError(gettext_noop("%(compute)s is in maintenance: Balance leaves it out"),
                                      compute=host.name)

    def validate(self, user, params):
        super().validate(user, params)
        if any(source == target for _vm, source, target in self.moves(params)):
            raise util.OperationError(gettext_noop("A VM is already on its destination"))

    def plan(self, user, params):
        names = Compute.objects.filter(pk__in=self.hosts(params)).order_by("name").values_list("name", flat=True)
        return Plan(claims={claims.bulk_migrate_key(): Claim.EXCLUSIVE}, resource=claims.bulk_migrate_key(),
                    label=", ".join(names), intent={"migrations": {}, "where": _where(self.hosts(params))})

    def log_entry(self, op, state):
        message = f"Balance {op.resource_label}: {len(op.params['moves'])} VMs"
        return "", "", "", message if state == Operation.SUCCEEDED else f"{message} ({state})"
