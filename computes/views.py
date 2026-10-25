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
from vrtManager.connection import wvmConnect
from vrtManager.hostdetails import wvmHostDetails

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


@superuser_only
def computes(request):
    """The computes, with what each has given its VMs."""
    computes = list(Compute.objects.order_by("name"))
    for compute in computes:
        given = compute.capacity
        if given:
            given["ratio"] = given["vcpus"]["all"] / given["cpus"] if given["cpus"] else 0
            # the memory bar: running and shut-off VMs' memory, and a mark at the
            # host's memory, on a scale that holds whichever is larger
            assigned, memory = given["assigned"], given["memory"]
            scale = max(assigned["all"], memory) or 1
            given["bar"] = {"running": assigned["running"] * 100 / scale,
                            "stopped": (assigned["all"] - assigned["running"]) * 100 / scale,
                            "host": memory * 100 / scale, "over": assigned["all"] > memory}
            given["memory_percent"] = round(assigned["all"] * 100 / memory) if memory else 0
            pools = sorted(given["pools"], key=lambda pool: pool["name"])
            for pool in pools:
                pool["used_percent"] = (pool["size"] - pool["free"]) * 100 / pool["size"] if pool["size"] else 0
            # the default pool shows; the others (a host may have dozens) open on a click
            given["pool"] = next((pool for pool in pools if pool["name"] == "default"), pools[0] if pools else None)
            given["more_pools"] = [pool for pool in pools if pool is not given["pool"]]
    return render(request, "computes/list.html", {"computes": computes})


@superuser_only
def overview(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)
    # the connection itself, not a TCP probe: ssh aliases and ProxyJump hosts
    # are not reachable by name and port from here
    status = "true" if compute.status else "false"

    conn = wvmHostDetails(
        compute.hostname,
        compute.login,
        compute.password,
        compute.type,
    )
    (
        hostname,
        host_arch,
        host_memory,
        logical_cpu,
        model_cpu,
        uri_conn,
    ) = conn.get_node_info()
    hypervisor = conn.get_hypervisors_domain_types()
    mem_usage = conn.get_memory_usage()
    emulator = conn.get_emulator(host_arch)
    version = conn.get_version()
    lib_version = conn.get_lib_version()
    conn.close()

    return render(request, "overview.html", locals())


@superuser_only
def instances(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)

    utils.refresh_instance_database(compute)
    instances = Instance.objects.filter(compute=compute).prefetch_related(
        "userinstance_set"
    )

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
        self.conn = wvmConnect(
            self.compute.hostname,
            self.compute.login,
            self.compute.password,
            self.compute.type,
        )

    def get_machine_types(self, arch):
        data = dict()
        try:
            data["machines"] = self.conn.get_machine_types(arch)
        except libvirtError:
            pass

        return json.dumps(data)

    def get_disk_buses(self, arch, machine, disk):
        data = dict()
        try:
            disk_device_types = self.conn.get_disk_device_types(arch, machine)

            if disk in disk_device_types:
                if disk == "disk":
                    data["bus"] = sorted(self.conn.get_disk_bus_types(arch, machine))
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
