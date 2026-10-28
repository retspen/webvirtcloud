import json

from admin.decorators import superuser_only
from django.conf import settings
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from instances.models import Instance
from libvirt import libvirtError
from logs.audit import audit, changed_fields, snapshot
from operations import claims
from vrtManager.connection import CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.storage import wvmStorages

from computes.forms import (
    SocketComputeForm,
    SshComputeForm,
    TcpComputeForm,
    TlsComputeForm,
)
from computes.models import Compute

from . import utils

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


@superuser_only
def computes(request):
    """The computes, with what each has given its VMs, and the totals of the
    ones the panel reaches."""
    computes = list(Compute.objects.order_by("name"))
    totals = {"hosts": len(computes), "connected": 0, "vms": 0, "running": 0,
              "vcpus": 0, "cpus": 0, "assigned": 0, "memory": 0}
    for compute in computes:
        compute.connection_name = CONNECTIONS.get(compute.type, "")
        compute.shown_capacity = given = shown_capacity(compute)
        totals["connected"] += compute.status is True
        if given:
            totals["vms"] += given["vm_count"]
            totals["running"] += given["vms"]["running"]
            totals["vcpus"] += given["vcpus"]["all"]
            totals["cpus"] += given["cpus"]
            totals["assigned"] += given["assigned"]["all"]
            totals["memory"] += given["memory"]
    return render(request, "computes/list.html", {"computes": computes, "totals": totals})


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
    context = {"compute": compute, "connected": compute.status is True}
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
            conn.close()
        except libvirtError as error:
            context["read_error"] = str(error)
        context["given"] = shown_capacity(compute)
        context["storage"] = host_pools(compute)
    return render(request, "overview.html", context)


@superuser_only
def instances(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)

    utils.refresh_instance_database(compute)
    instances = Instance.objects.filter(compute=compute).order_by("name").prefetch_related("userinstance_set")

    return render(
        request, "computes/instances.html",
        {"compute": compute, "instances": instances, "job_resource": claims.compute_key(compute.id)},
    )


@superuser_only
def compute_create(request, FormClass):
    form = FormClass(request.POST or None)
    if form.is_valid():
        compute = form.instance
        with audit(request, compute, f"Compute {compute.name} ({compute.hostname})", "add"):
            form.save()
        return redirect(reverse("computes"))

    return render(request, "computes/form.html", {"form": form})


@superuser_only
def compute_update(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)

    if compute.type == 1:
        FormClass = TcpComputeForm
    elif compute.type == 2:
        FormClass = SshComputeForm
    elif compute.type == 3:
        FormClass = TlsComputeForm
    elif compute.type == 4:
        FormClass = SocketComputeForm

    subject = f"Compute {compute.name} ({compute.hostname})"
    before = snapshot(compute)
    form = FormClass(request.POST or None, instance=compute)
    if form.is_valid():
        with audit(request, compute, subject, "change") as entry:
            form.save()
            fields = changed_fields(before, snapshot(compute))
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields
        return redirect(reverse("computes"))

    return render(request, "computes/form.html", {"form": form})


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
    return HttpResponse(comp_mgr.get_disk_buses(arch, machine, disk), content_type="application/json")


def get_compute_machine_types(request, compute_id, arch):
    """
    :param request:
    :param compute_id:
    :param arch:
    :return:
    """
    comp_mgr = ComputeManager(compute_id)
    return HttpResponse(comp_mgr.get_machine_types(arch), content_type="application/json")


class ComputeManager:
    def __init__(self, compute_id):
        self.compute = get_object_or_404(Compute, pk=compute_id)

    def get_machine_types(self, arch):
        data = dict()
        try:
            data["machines"] = self.compute.proxy.get_machine_types(arch)
        except libvirtError:
            pass

        return json.dumps(data)

    def get_disk_buses(self, arch, machine, disk):
        data = dict()
        try:
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
        except libvirtError:
            pass

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
        result = {"cpudata": None, "memdata": {"total": None, "usage": None}, "timeline": timezone.now().strftime("%H:%M:%S")}
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
                "timeline": timezone.now().strftime("%H:%M:%S"),
                "window": round(cpu["window"], 1),
                "cpu_sample": CPU_SAMPLE_SIGNER.sign_object(
                    {"compute": self.compute.id, "idle": idle, "total": total, "time": taken}
                ),
            }
            conn.close()
        except libvirtError:
            pass

        return json.dumps(result)
