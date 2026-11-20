import json
import logging
import threading
import time
from collections import Counter
from datetime import timedelta
from contextlib import suppress
from copy import copy

from admin.decorators import superuser_only
from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST
from webvirtcloud.middleware import error_text
from instances.models import Instance
from instances.utils import read_list_rows, vm_states
from libvirt import libvirtError
from logs.audit import audit, changed_fields, snapshot
from operations import claims, jobs
from operations.models import Operation
from operations.utils import busy_message, say
from vmbackups.models import Backup, BackupRun
from vmbackups.schedule import IN_MAINTENANCE
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.storage import wvmStorages

from computes.forms import (
    SocketComputeForm,
    SshComputeForm,
    TcpComputeForm,
    TlsComputeForm,
)
from computes.models import ENDPOINT, Compute, Tag

from . import utils

logger = logging.getLogger(__name__)

# The host CPU graph sends back the CPU sample of its previous answer; usage
# is taken since then when it is this recent, otherwise over one second.
CPU_SAMPLE_MAX_AGE = 15
CPU_SAMPLE_SIGNER = signing.TimestampSigner(salt="computes.cpu-sample")


def shown_capacity(compute):
    """The compute's capacity, with what its bars show; None when it cannot
    be read."""
    given = compute.capacity
    if given:
        # the memory bar: running and shut-off VMs' memory, on a scale that
        # holds the host's memory or all given, whichever is larger
        assigned, memory = given["assigned"], given["memory"]
        assigned["stopped"] = assigned["all"] - assigned["running"]
        scale = max(assigned["all"], memory) or 1
        given["bar"] = {"running": assigned["running"] * 100 / scale, "stopped": assigned["stopped"] * 100 / scale,
                        "over": assigned["all"] > memory}
        given["memory_percent"] = round(assigned["all"] * 100 / memory) if memory else 0
        # the vCPU bar likewise: running and shut-off VMs' vCPUs against the CPUs
        vcpus, cpus = given["vcpus"], given["cpus"]
        vcpus["stopped"] = vcpus["all"] - vcpus["running"]
        cpu_scale = max(vcpus["all"], cpus) or 1
        given["cpu_bar"] = {"running": vcpus["running"] * 100 / cpu_scale, "stopped": vcpus["stopped"] * 100 / cpu_scale}
        given["vm_count"] = sum(given["vms"].values())
        # the VMs that keep a host in maintenance from being ready: all but the shut-off ones
        given["active"] = given["vm_count"] - given["vms"]["shutoff"]
    return given


def host_pools(compute):
    """The compute's active storage pools, measured now: the default one (else
    the first) to show, the others (a host may have dozens) to open on a
    click; or None when they cannot be read."""
    try:
        storages = wvmStorages(compute.hostname, compute.login, compute.password, compute.type)
        pools = [pool for pool in storages.get_storages_info() if pool["status"]]
    except libvirtError:
        return None
    pools.sort(key=lambda pool: (pool["name"] != "default", pool["name"]))
    return {"pool": pools[0] if pools else None, "more_pools": pools[1:]}


# how the panel reaches a compute, by Compute.type
CONNECTIONS = {CONN_TCP: "TCP", CONN_SSH: "SSH", CONN_TLS: "TLS", CONN_SOCKET: "Socket"}


# the Computes page reads its hosts side by side, and waits this long for them in all
LIST_WAIT = 10


# what the box above the hosts tells of: a pool this full (percent), a snapshot this old
POOL_FULL = 85
SNAPSHOT_OLD = timedelta(days=30)


def _read_host(compute):
    """Whether the panel reaches the compute, why not, its capacity
    (shown_capacity) and, for one whose host UUID is not kept yet, that UUID
    ("" when it cannot be read): every libvirt read of the list, bounded."""
    uuid = ""
    if compute.status is True and not compute.host_uuid:
        with suppress(libvirtError):
            uuid = compute.proxy.host_uuid()
    return compute.status, compute.connection_error, shown_capacity(compute), uuid


def _read_attention(compute):
    """The compute's full pools and old snapshots (get_attention); None when
    they cannot be read."""
    if compute.status is True:
        with suppress(libvirtError):
            return compute.proxy.get_attention(POOL_FULL, timezone.now() - SNAPSHOT_OLD)
    return None


def _read_needs(compute):
    """What the compute's VMs need of another host and what it has (migration_needs); None when
    they cannot be read. Read apart from _read_attention: a slow or failed read hides no pool."""
    if compute.status is True:
        with suppress(libvirtError):
            return compute.proxy.migration_needs()
    return None


class _HostRead(threading.Thread):
    """One read of a host (read: _read_host, _read_attention or _read_needs) on a daemon
    thread: one stuck on its host does not hold the process when it exits."""

    def __init__(self, compute, read, stand_in=(None, 0)):
        super().__init__(daemon=True, name=f"wvc-host-{compute.pk}")
        self.compute, self.read, self.result, self.ended = compute, read, None, None
        self.stand_in = stand_in  # a "needs" read's: (the result, when it ended) of the one before, if it read

    def run(self):
        self.result = self.read(self.compute)
        self.ended = time.monotonic()


# the reads of the Computes pages of this process, one of a host at a time: a host that
# hangs holds one thread however often the page is loaded, and no other host's
_reading = {}  # (its kind, compute pk, its connection settings): its last read
_reading_lock = threading.Lock()

# the box's reads (_read_attention, _read_needs) are waited for this long at most: one slow does not hold the page
ATTENTION_WAIT = 2
# what a host's VMs need is read again on each load; the last read that ended stands in for this
# long (seconds) when the new one outlasts ATTENTION_WAIT, so a host of many VMs is still compared
NEEDS_KEPT = 300
NEEDS_GRACE = 0.5  # how long a new read is waited for when one stands in for it (seconds)

READ_KINDS = ("host", "attention", "needs")  # _read_host, _read_attention, _read_needs


def _read_key(compute):
    """A compute as read: a compute whose connection settings change is read anew, not
    given what its old host answered."""
    return (compute.pk, *(getattr(compute, field) for field in ENDPOINT))


def _start(compute, kind):
    """compute's read of kind (READ_KINDS): one of an earlier load still running, else a new one.
    Callers hold _reading_lock."""
    key = (kind, *_read_key(compute))
    read = _reading.get(key)
    if read is None or not read.is_alive():
        # a "needs" read that ended stands in for the new one; one that failed leaves none
        stand_in = (read.result, read.ended) if kind == "needs" and read is not None and read.result is not None \
            else (None, 0)
        _reading[key] = _HostRead(copy(compute), {"host": _read_host, "attention": _read_attention,
                                                  "needs": _read_needs}[kind], stand_in)
        _reading[key].start()
    return _reading[key]


def _stand_in(read):
    """What the read of what VMs need before read said, if it ended within NEEDS_KEPT, else None."""
    result, ended = read.stand_in
    return result if time.monotonic() - ended < NEEDS_KEPT else None


def read_hosts(computes, attention=False):
    """Reads each of computes (_read_host) on its own thread: a slow host
    holds back only itself, and one not read within LIST_WAIT is shown as
    not answering. A host whose read of an earlier load still runs is not
    read again: that read is waited for. Each thread reads a copy: one still
    running later does not change what the page shows. With attention, each
    one's full pools and old snapshots too (_read_attention, compute.attention),
    waited for up to ATTENTION_WAIT: None for one that comes later."""
    with _reading_lock:
        keys = {(kind, *_read_key(compute)) for compute in computes for kind in READ_KINDS}
        # reads ended of computes deleted or changed since: their copies (and credentials) go
        for key in [key for key, read in _reading.items() if key not in keys and not read.is_alive()]:
            del _reading[key]
        reads = {compute: _start(compute, "host") for compute in computes}
        scans = {compute: _start(compute, "attention") for compute in computes} if attention else {}
        needs = {compute: _start(compute, "needs") for compute in computes} if attention else {}
        stand_ins = {compute: _stand_in(read) for compute, read in needs.items()}
    started = time.monotonic()
    for read in reads.values():
        read.join(max(0, started + LIST_WAIT - time.monotonic()))
    for scan in scans.values():
        scan.join(max(0, started + ATTENTION_WAIT - time.monotonic()))
    # a host's needs with a stand-in are waited for NEEDS_GRACE at most, not ATTENTION_WAIT; those of a
    # host that does not answer not at all: they are not told
    for compute, read in needs.items():
        if reads[compute].result is not None and reads[compute].result[0] is True:
            read.join(max(0, started + (ATTENTION_WAIT if stand_ins[compute] is None else NEEDS_GRACE) - time.monotonic()))
    for compute, read in reads.items():
        compute.attention = scans[compute].result if compute in scans else None
        # this load's read if it ended, else the stand-in
        compute.needs = (stand_ins[compute] if needs[compute].is_alive() else needs[compute].result) \
            if compute in needs else None
        if read.result is not None:
            compute.status, compute.connection_error, compute.shown_capacity, compute.read_uuid = read.result
            if compute.status is not True:  # what it said before it stopped answering is not told
                compute.attention = compute.needs = None
        else:
            compute.status, compute.shown_capacity, compute.read_uuid, compute.attention = False, None, "", None
            compute.needs = None
            compute.connection_error = _("The host did not answer within %(seconds)s seconds") % {"seconds": LIST_WAIT}


@superuser_only
def computes(request):
    """The computes, with what each has given its VMs, and the totals of the
    ones the panel reaches."""
    computes = list(Compute.objects.order_by("name").prefetch_related("tags"))
    totals = {"hosts": len(computes), "connected": 0, "vms": 0, "running": 0,
              "vcpus": 0, "cpus": 0, "assigned": 0, "memory": 0}
    read_hosts(computes, attention=True)
    for compute in computes:
        compute.connection_name = CONNECTIONS.get(compute.type, "")
        if compute.read_uuid:
            # one added before host UUIDs were kept (Compute.clean); none for a second record of a host
            with suppress(IntegrityError):
                compute.record_host(compute.read_uuid)
        given = compute.shown_capacity
        totals["connected"] += compute.status is True
        if given:
            totals["vms"] += given["vm_count"]
            totals["running"] += given["vms"]["running"]
            totals["vcpus"] += given["vcpus"]["all"]
            totals["cpus"] += given["cpus"]
            totals["assigned"] += given["assigned"]["all"]
            totals["memory"] += given["memory"]
    return render(request, "computes/list.html",
                  {"computes": computes, "totals": totals, "job_resource": claims.bulk_migrate_key(),
                   "tags": Tag.counts(computes), "attention": attention(computes)})


def attention(computes):
    """What wants a look, for the box above the hosts; empty when nothing: the
    computes not answering, their full pools and old snapshots (_read_attention),
    the backup jobs that failed and the backups a schedule did not take in the last 7 days
    (not for a host in maintenance: the operator's choice), the backups missing
    or damaged, and the jobs that ended uncertain or wait for over an hour."""
    week = timezone.now() - timedelta(days=7)
    vms = {(vm.compute_id, vm.name): vm for vm in Instance.objects.filter(compute__in=computes)}
    found = {
        "hosts": [c for c in computes if c.status is not True],
        "pools": [(c, pool) for c in computes for pool in (c.attention or {}).get("pools", [])],
        "snapshots": [(c, vms.get((c.pk, s["vm"])), s) for c in computes for s in (c.attention or {}).get("snapshots", [])],
        "failed": Operation.objects.filter(kind="backup.create", state=Operation.FAILED, finished_at__gte=week).count(),
        "not_taken": sorted(Counter(run.policy for run in BackupRun.objects.filter(
            day__gte=timezone.localtime(week).date(), state__in=(BackupRun.SKIPPED, BackupRun.FAILED)
        ).select_related("policy") if run.note != say(IN_MAINTENANCE)).items(), key=lambda item: item[0].name),
        "missing": Backup.objects.filter(state=Backup.MISSING).count(),
        "damaged": Backup.objects.filter(state=Backup.READY).exclude(damage=[]).count(),
        "uncertain": Operation.objects.filter(state=Operation.UNCERTAIN).count(),
        "waiting": Operation.objects.filter(state=Operation.QUEUED, created_at__lt=timezone.now() - timedelta(hours=1)).count(),
    }
    found["lacking"] = lacking(computes)
    return found if any(found.values()) else {}


def lacking(computes):
    """[(host, other host, [what])]: what the VMs of a host use (migration_needs) that the other
    host lacks or has otherwise, so that the migration check refuses moving them there: an active
    network, a network filter or one of other rules, a secret (by UUID or usage). Only hosts that
    answer and whose needs were read, and of these only the listings read; a host in maintenance
    is no destination, but its VMs still need one."""
    needs = {c: c.needs for c in computes if c.status is True and c.needs}
    found = []
    for source, need in needs.items():
        for target, other in needs.items():
            if target is source or target.maintenance or need["uses"] is None:  # its VMs not read: no source
                continue
            uses, has, own = need["uses"], other["has"], need["has"]["filters"] or {}
            what = []
            if has["networks"] is not None:
                what.append((gettext_noop("no active network %(names)s"), sorted(set(uses["networks"]) - set(has["networks"]))))
            if has["filters"] is not None:
                what.append((gettext_noop("no network filter %(names)s"), sorted(set(uses["filters"]) - set(has["filters"]))))
                # compared only with the source's own filter: one it lacks too is not another's rules
                what.append((gettext_noop("network filter %(names)s with other rules"),
                             sorted(n for n in uses["filters"] if n in has["filters"] and n in own and has["filters"][n] != own[n])))
            if has["secrets"] is not None:
                usages = {tuple(usage) for usage in has["usages"]}
                what.append((gettext_noop("no secret %(names)s"),
                             sorted([*(set(uses["secrets"]) - set(has["secrets"])),
                                     *(usage for usage_type, usage in uses["usages"] if (usage_type, usage) not in usages)])))
            what = [_(text) % {"names": ", ".join(names)} for text, names in what if names]
            if what:
                found.append((target, source, what))
    return found


@superuser_only
def capacity(request, compute_id):
    """One line of what the compute has given its VMs, as plain text, for the
    new-VM dialog."""
    compute = get_object_or_404(Compute, pk=compute_id)
    return render(request, "computes/capacity_line.txt", {"given": compute.capacity}, content_type="text/plain; charset=utf-8")


@superuser_only
def overview(request, compute_id):
    """The host's page: whether the panel reaches it, its VMs, what it has
    given them, its load, hardware and software. A host it cannot reach
    keeps the page, with the reason and its connection to edit."""
    compute = get_object_or_404(Compute, pk=compute_id)
    # the connection itself, not a TCP probe: ssh aliases and ProxyJump hosts
    # are not reachable by name and port from here
    context = {"compute": compute, "connected": compute.status is True,
               # in maintenance, the host's latest bulk migration of that maintenance, or one still running:
               # whether its VMs are being moved, or how that ended
               "bulk": Operation.objects.filter(kind="host.bulk_migrate", resource=claims.compute_key(compute.pk))
               .filter(Q(created_at__gte=compute.maintenance_since) | Q(state__in=Operation.ACTIVE))
               .order_by("-created_at").first() if compute.maintenance else None}
    context["bulk_running"] = context["bulk"] is not None and context["bulk"].state in Operation.ACTIVE
    if context["connected"]:
        try:
            conn = wvmHostDetails(compute.hostname, compute.login, compute.password, compute.type)
            hostname, arch, memory, _cpus, processor, uri = conn.get_node_info()
            topology = conn.get_cpu_topology()
            context["host"] = {
                "hostname": hostname, "arch": arch, "memory": memory, "processor": processor, "uri": uri,
                "topology": topology, "ghz": round(topology["mhz"] / 1000, 1),
                "hypervisor": conn.wvm.getType(), "hypervisor_version": conn.get_version(),
                "libvirt_version": conn.get_lib_version(),
                "emulator": conn.get_emulator(arch), "guest_archs": conn.get_hypervisors_domain_types(),
            }
        except libvirtError as error:
            context["read_error"] = str(error)
        context["given"] = shown_capacity(compute)
        context["storage"] = host_pools(compute)
        if compute.maintenance:
            # libvirt starts these itself when the host boots: the panel cannot refuse that
            with suppress(libvirtError):
                context["autostart"] = sorted(dom.name() for dom in compute.proxy.wvm.listAllDomains() if dom.autostart())
    return render(request, "overview.html", context)


@superuser_only
def instances(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)
    # read first: the poll's first answer then tells a change made while the page was read
    states = vm_states(request.user, [compute])
    utils.refresh_instance_database(compute)
    instances = list(Instance.objects.filter(compute=compute).order_by("name").prefetch_related("userinstance_set", "tags"))
    read_list_rows(instances, [compute])

    return render(
        request, "computes/instances.html",
        {"compute": compute, "instances": instances, "job_resource": claims.compute_key(compute.id),
         "states_url": reverse("instances:states") + f"?compute={compute.id}", "vm_states": states},
    )


def read_fleet():
    """The computes; those the panel reads now, {pk: compute}, read side by
    side and bounded (one that does not answer is left out); their VMs, with
    their info; what each gives its running VMs, {pk: [memory KiB, vCPUs]};
    the memory KiB its running and paused VMs, also those the panel does not
    list, leave of its memory, {pk: KiB}; and its size, {pk: (memory KiB,
    CPUs)}."""
    computes = list(Compute.objects.order_by("name"))
    read_hosts(computes)
    hosts = {compute.pk: compute for compute in computes if compute.status is True and compute.shown_capacity}
    for compute in hosts.values():
        utils.refresh_instance_database(compute)
    instances = list(Instance.objects.filter(compute__in=hosts).order_by("name"))
    read_list_rows(instances, hosts.values())
    loads = {pk: [0, 0] for pk in hosts}
    for instance in instances:
        if instance.info and instance.info[0] == 1:
            loads[instance.compute_id][0] += instance.info[2]
            loads[instance.compute_id][1] += instance.info[3]
    room = {pk: (compute.shown_capacity["memory"] - compute.shown_capacity["assigned"]["running"]) // 1024
            for pk, compute in hosts.items()}
    sizes = {pk: (compute.shown_capacity["memory"] // 1024, compute.shown_capacity["cpus"]) for pk, compute in hosts.items()}
    return computes, hosts, instances, loads, room, sizes


@superuser_only
def bulk_migrate(request, compute_id):
    """Migrates the chosen VMs of the host in one job, for the host's
    maintenance: a migrate job each, the chosen number at once; a running VM
    live, a shut-off one offline. They go to one host, or are spread over the
    others (computes.balance.spread), where the page shows each one going: a
    VM ticked or unticked then makes the spread again, as the form sends the
    VMs it showed ("shown") and the ticked ones ("vm"). A VM with a disk file
    the hosts do not share is not offered: it takes a copy, chosen on its
    own Migrate tab.

    Asked from the host's "Put in maintenance" ("maintenance"), the page
    puts the host in maintenance with the job, in one transaction: with
    the job admitted, or not at all."""
    from computes.balance import spread
    from computes.jobs import parallel_limit
    from computes.reach import Reach

    compute = get_object_or_404(Compute, pk=compute_id)
    # a host in maintenance takes no VM (Compute.refuse_new_vms)
    targets = list(Compute.objects.exclude(pk=compute.pk).filter(maintenance_since=None).order_by("name"))
    if request.method == "POST":
        chosen = request.POST.getlist("instance")
        if request.POST.get("spread"):
            moves, again = list(zip(chosen, request.POST.getlist("target"))), "spread"
        else:
            # the destination the form showed, not another one taken in its place
            target = get_object_or_404(Compute.objects.exclude(pk=compute.pk), pk=request.POST.get("target", "") or None)
            moves, again = [(pk, target.pk) for pk in chosen], target.pk
        entering = request.POST.get("maintenance") == "on"
        raw = {"compute": compute.pk, "parallel": request.POST.get("parallel", ""), "moves": moves, "maintenance": entering}
        key = request.POST.get("submission_key", "")
        try:
            with transaction.atomic():
                Compute.objects.select_for_update().filter(pk=compute.pk).first()  # one maintenance change at a time
                # a form sent again finds its job: it does not put back a host taken out of maintenance since;
                # one sent after its key expired makes a new job, and puts it in maintenance with it
                found = Operation.objects.filter(user=request.user, submission_key=key).values_list("pk", flat=True).first()
                op = jobs.submit("host.bulk_migrate", request.user, raw, key)
                if entering and op.pk != found:
                    with audit(request, compute, f"Compute {compute.name}", "maintenance on"):
                        Compute.objects.filter(pk=compute.pk).update(maintenance_since=op.created_at)
        except claims.Busy as busy:
            messages.error(request, busy_message(busy, request.user))
        except (ValueError, jobs.SubmissionConflict, libvirtError) as err:
            messages.error(request, error_text(request, err))
        else:
            jobs.remember_job(request, op)
            return redirect("instances", compute.pk)
        return redirect(reverse("bulk_migrate", args=[compute.pk]) + f"?target={again}"
                        + ("&maintenance=on" if entering else ""))

    entering = request.GET.get("maintenance") == "on" and not compute.maintenance
    reach = Reach(request)
    spreading = len(targets) > 1 and request.GET.get("target", "spread") == "spread"
    utils.refresh_instance_database(compute)
    instances = list(Instance.objects.filter(compute=compute).order_by("name").prefetch_related("tags"))
    read_list_rows(instances, [compute])
    tags = sorted({tag.name for instance in instances for tag in instance.tags.all()})
    if not spreading:
        target = next((t for t in targets if str(t.pk) == request.GET.get("target")), targets[0] if targets else None)
        for instance in instances if target else ():
            instance.refusal = reach.refusal(instance, target)
        return render(request, "computes/bulk_migrate.html",
                      {"compute": compute, "targets": targets, "target": target, "instances": instances, "tags": tags,
                       "parallel": range(1, parallel_limit() + 1), "entering": entering})

    # the other hosts' loads: the VMs of this one are read above, also when its capacity cannot be
    _computes, hosts, _instances, loads, room, sizes = read_fleet()
    others = {pk: host for pk, host in hosts.items() if pk != compute.pk and not host.maintenance}
    shown, ticked = request.GET.getlist("shown"), request.GET.getlist("vm")
    vms = []
    for instance in instances:
        refusals = {host: reach.refusal(instance, host) for host in others.values()}
        can_go = {host.pk for host, refusal in refusals.items() if refusal is None}
        if not can_go:
            instance.refusal = "; ".join(f"{host.name}: {refusal}" for host, refusal in refusals.items())
            continue
        instance.refusal = None
        shut_off = bool(instance.info) and instance.info[0] == 5
        # at first the VMs that are not shut off, as with one destination; then the ticked ones
        if instance.info and (str(instance.pk) in ticked if shown else not shut_off):
            vms.append((instance.pk, instance.info[2], instance.info[3], not shut_off, can_go))
    placed, _after = spread({pk: loads[pk] for pk in others}, vms, {pk: room[pk] for pk in others}, sizes)
    for instance in instances:
        instance.target = others.get(placed.get(instance.pk))
        if instance.target is None and any(vm[0] == instance.pk for vm in vms):
            instance.note = _("No other host has room for it")
    going = [instance for instance in instances if instance.target]
    return render(request, "computes/bulk_migrate.html",
                  {"compute": compute, "targets": targets, "spreading": True, "instances": instances, "entering": entering,
                   "tags": tags,
                   "all_ticked": len(going) == len([instance for instance in instances if not instance.refusal]),
                   "shut_off_ticked": any(instance.info[0] == 5 for instance in going),
                   "unreachable": [host for host in targets if host.pk not in others],
                   "parallel": range(1, parallel_limit() + 1)})


@superuser_only
def balance(request):
    """Proposes migrations of running VMs that even out the share of their
    memory, then of their CPUs, the hosts give their running VMs
    (computes.balance), and
    runs the proposal shown in one job. A VM unticked stays where it is and
    the proposal is made again without it: the form sends the VMs it showed
    ("shown") and the ticked ones ("vm")."""
    from computes.balance import propose
    from computes.jobs import parallel_limit
    from computes.reach import Reach

    if request.method == "POST":
        moves = zip(request.POST.getlist("instance"), request.POST.getlist("source"), request.POST.getlist("target"))
        raw = {"parallel": request.POST.get("parallel", ""), "moves": list(moves)}
        try:
            op = jobs.submit("host.balance", request.user, raw, request.POST.get("submission_key", ""))
        except claims.Busy as busy:
            messages.error(request, busy_message(busy, request.user))
        except (ValueError, jobs.SubmissionConflict, libvirtError) as err:
            messages.error(request, error_text(request, err))
        else:
            jobs.remember_job(request, op)
            return redirect("computes")
        return redirect("balance")

    computes, hosts, instances, loads, room, sizes = read_fleet()
    # a host in maintenance is left out: its VMs neither count nor move, and it takes none
    resting = [hosts.pop(pk) for pk in [pk for pk, compute in hosts.items() if compute.maintenance]]
    loads, room, sizes = ({pk: part[pk] for pk in hosts} for part in (loads, room, sizes))
    running = [instance for instance in instances
               if instance.info and instance.info[0] == 1 and instance.compute_id in hosts]
    pinned = set(request.GET.getlist("shown")) - set(request.GET.getlist("vm"))
    movable, unmovable, reach = [], [], Reach(request)
    for instance in running:
        if str(instance.pk) in pinned:
            continue
        refusals = {target: reach.refusal(instance, target)
                    for target in hosts.values() if target.pk != instance.compute_id}
        targets = {target.pk for target, refusal in refusals.items() if refusal is None}
        if targets:
            movable.append((instance.pk, instance.compute_id, instance.info[2], instance.info[3], targets))
        elif refusals:
            instance.refusals = [f"{target.name}: {refusal}" for target, refusal in refusals.items()]
            unmovable.append(instance)
    moves, after = propose(loads, movable, room, sizes)
    # the bars: the share of each host's memory before and after
    for pk, compute in hosts.items():
        compute.before, compute.after, compute.size = loads[pk], after[pk], sizes[pk]
        compute.bars = [min(load[0] * 100 / max(sizes[pk][0], 1), 100) for load in (loads[pk], after[pk])]
    by_pk = {instance.pk: instance for instance in running}
    for vm, _source, target in moves:
        by_pk[vm].target = hosts[target]
    return render(request, "computes/balance.html", {
        "hosts": hosts.values(), "resting": resting,
        "unreachable": [compute for compute in computes if compute.pk not in hosts and compute not in resting],
        "moves": [by_pk[vm] for vm, _source, _target in moves],
        "pinned": [instance for instance in running if str(instance.pk) in pinned],
        "unmovable": unmovable, "parallel": range(1, parallel_limit() + 1)})


# the form of each kind of compute, by Compute.type
FORMS = {form.conn_type: form for form in (TcpComputeForm, SshComputeForm, TlsComputeForm, SocketComputeForm)}


def saved(request, form):
    """Tells that the panel cannot connect to the compute the form saved, and why (Compute.clean)."""
    if form.instance.unreachable:
        messages.warning(request, _("The host was saved, but the panel cannot connect to it: %(error)s")
                         % {"error": form.instance.unreachable})
    return redirect(reverse("computes"))


@sensitive_post_parameters()
@superuser_only
def compute_create(request, FormClass):
    form = FormClass(request.POST or None)
    if request.method == "POST":
        with utils.hosts_lock():
            if form.is_valid():
                compute = form.instance
                with audit(request, compute, f"Compute {compute.name} ({compute.hostname})", "add"):
                    form.save()
                return saved(request, form)

    return render(request, "computes/form.html", {"form": form})


@sensitive_post_parameters()
@superuser_only
def compute_update(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)

    FormClass = FORMS[compute.type]
    subject = f"Compute {compute.name} ({compute.hostname})"
    before = snapshot(compute)
    form = FormClass(request.POST or None, instance=compute)
    if request.method == "POST":
        # held as a delete holds it: a job on the compute keeps the host it was admitted for
        with audit(request, compute, subject, "change") as entry, utils.hosts_lock(compute):
            entry.skip = True  # a refused form changes nothing
            if form.is_valid():
                form.save()
                fields = changed_fields(before, snapshot(compute))
                entry.action = "change " + ", ".join(fields)
                entry.skip = not fields
        if form.is_valid():
            return saved(request, form)

    return render(request, "computes/form.html", {"form": form})


@require_POST
@superuser_only
def maintenance(request, compute_id):
    """Puts the host in maintenance or takes it out (Compute.maintenance), as
    the form asks: the state it names, not the other one of the moment, so
    a second page sent meanwhile does not turn it back."""
    compute = get_object_or_404(Compute, pk=compute_id)
    wanted = request.POST.get("maintenance") == "on"
    action = "maintenance on" if wanted else "maintenance off"
    with audit(request, compute, f"Compute {compute.name}", action):
        if wanted:  # already in maintenance: since then still
            Compute.objects.filter(pk=compute.pk, maintenance_since=None).update(maintenance_since=timezone.now())
        else:
            Compute.objects.filter(pk=compute.pk).update(maintenance_since=None)
    return redirect("overview", compute.pk)


@superuser_only
def compute_delete(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)
    if request.method == "POST":
        with audit(request, compute, f"Compute {compute.name} ({compute.hostname})", "delete"):
            compute.delete()
        return redirect("computes")

    return render(
        request,
        "common/confirm_delete.html",
        {"object": compute,
         "consequence": _("Its VMs keep running on the host and leave the panel; their owners are kept for "
                          "%(days)s days on the Removed VMs page and come back if the host is added again.")
                        % {"days": getattr(settings, "INSTANCE_OWNERSHIP_RETENTION_DAYS", 30)}},
    )


def compute_graph(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """
    comp_mgr = ComputeManager(compute_id)
    data = comp_mgr.compute_graph(request.GET.get("cpu_sample"))

    return HttpResponse(data, content_type="application/json")


def get_compute_disk_buses(request, compute_id, arch, machine, disk):
    """
    :param request:
    :param compute_id:
    :param arch:
    :param machine:
    :param disk:
    :return:
    """
    comp_mgr = ComputeManager(compute_id)
    try:
        return HttpResponse(comp_mgr.get_disk_buses(arch, machine, disk), content_type="application/json")
    except libvirtError as err:
        return read_failed(comp_mgr.compute, "disk buses", err)


def get_compute_machine_types(request, compute_id, arch):
    """
    :param request:
    :param compute_id:
    :param arch:
    :return:
    """
    comp_mgr = ComputeManager(compute_id)
    try:
        return HttpResponse(comp_mgr.get_machine_types(arch), content_type="application/json")
    except libvirtError as err:
        return read_failed(comp_mgr.compute, "machine types", err)


def read_failed(compute, what, err):
    """A list the new VM form loads that the host did not give: not 200 with
    an empty list, which the form cannot tell from none."""
    logger.warning("Reading the %s of compute %s failed: %s", what, compute.name, err)
    return JsonResponse({"error": str(err)}, status=400)


class ComputeManager:
    def __init__(self, compute_id):
        self.compute = get_object_or_404(Compute, pk=compute_id)

    def get_machine_types(self, arch):
        return json.dumps({"machines": self.compute.proxy.get_machine_types(arch)})

    def get_disk_buses(self, arch, machine, disk):
        data = dict()
        disk_device_types = self.compute.proxy.get_disk_device_types(arch, machine)

        if disk in disk_device_types:
            if disk == "disk":
                data["bus"] = sorted(self.compute.proxy.get_disk_bus_types(arch, machine))
            elif disk == "cdrom":
                data["bus"] = ["ide", "sata", "scsi"]
            elif disk == "floppy":
                data["bus"] = ["fdc"]
            elif disk == "lun":
                data["bus"] = ["scsi"]

        return json.dumps(data)

    def _cpu_sample(self, token):
        """The (idle, total, time) sample in a token of this compute's graph,
        or None when there is none, it is altered or too old."""
        if not token:
            return None
        try:
            data = CPU_SAMPLE_SIGNER.unsign_object(token, max_age=CPU_SAMPLE_MAX_AGE)
        except signing.BadSignature:
            return None
        if data.get("compute") != self.compute.id:
            return None
        return data["idle"], data["total"], data["time"]

    def compute_graph(self, cpu_sample=None):
        result = {"cpudata": None, "memdata": {"total": None, "usage": None}, "timeline": timezone.localtime().strftime("%H:%M:%S")}
        try:
            conn = wvmHostDetails(
                self.compute.hostname,
                self.compute.login,
                self.compute.password,
                self.compute.type,
            )
            cpu = conn.get_cpu_usage(previous=self._cpu_sample(cpu_sample))
            idle, total, taken = cpu["sample"]
            result = {
                "cpudata": cpu["usage"],
                "memdata": conn.get_memory_usage(),
                "timeline": timezone.localtime().strftime("%H:%M:%S"),  # the panel's time, as the VM charts
                "window": round(cpu["window"], 1),
                "cpu_sample": CPU_SAMPLE_SIGNER.sign_object(
                    {"compute": self.compute.id, "idle": idle, "total": total, "time": taken}
                ),
            }
        except libvirtError:
            pass

        return json.dumps(result)
