import json

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.urls import reverse
from django.utils import timezone
from libvirt import libvirtError

from accounts.models import UserInstance
from admin.decorators import superuser_only
from computes.forms import (SocketComputeForm, SshComputeForm, TcpComputeForm, TlsComputeForm)
from computes.models import Compute
from instances.models import Instance
from vrtManager.connection import (CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS, connection_manager, wvmConnect)
from vrtManager.hostdetails import wvmHostDetails

from . import utils


@superuser_only
def computes(request):
    """
    :param request:
    :return:
    """

    computes = Compute.objects.filter().order_by('name')

    return render(request, 'computes/list.html', {'computes': computes})


@superuser_only
def overview(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)
    status = 'true' if connection_manager.host_is_up(compute.type, compute.hostname) is True else 'false'

    conn = wvmHostDetails(
        compute.hostname,
        compute.login,
        compute.password,
        compute.type,
    )
    hostname, host_arch, host_memory, logical_cpu, model_cpu, uri_conn = conn.get_node_info()
    hypervisor = conn.get_hypervisors_domain_types()
    mem_usage = conn.get_memory_usage()
    emulator = conn.get_emulator(host_arch)
    version = conn.get_version()
    lib_version = conn.get_lib_version()
    conn.close()

    return render(request, 'overview.html', locals())


@superuser_only
def instances(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)

    utils.refresh_instance_database(compute)
    instances = Instance.objects.filter(compute=compute).prefetch_related('userinstance_set')

    return render(request, 'computes/instances.html', {'compute': compute, 'instances': instances})


@superuser_only
def compute_create(request, FormClass):
    form = FormClass(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect(reverse('computes'))

    return render(request, 'computes/form.html', {'form': form})


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

    form = FormClass(request.POST or None, instance=compute)
    if form.is_valid():
        form.save()
        return redirect(reverse('computes'))

    return render(request, 'computes/form.html', {'form': form})


@superuser_only
def compute_delete(request, compute_id):
    compute = get_object_or_404(Compute, pk=compute_id)
    if request.method == 'POST':
        compute.delete()
        return redirect('computes')

    return render(
        request,
        'common/confirm_delete.html',
        {'object': compute},
    )


def compute_graph(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """
    compute = get_object_or_404(Compute, pk=compute_id)
    try:
        conn = wvmHostDetails(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        current_time = timezone.now().strftime("%H:%M:%S")
        cpu_usage = conn.get_cpu_usage()
        mem_usage = conn.get_memory_usage()
        conn.close()
    except libvirtError:
        cpu_usage = {'usage': 0}
        mem_usage = {'usage': 0}
        current_time = 0

    data = json.dumps({
        'cpudata': cpu_usage['usage'],
        'memdata': mem_usage,
        'timeline': current_time,
    })
    response = HttpResponse()
    response['Content-Type'] = "text/javascript"
    response.write(data)
    return response


def get_compute_disk_buses(request, compute_id, arch, machine, disk):
    """
    :param request:
    :param compute_id:
    :param arch:
    :param machine:
    :param disk:
    :return:
    """
    data = dict()
    compute = get_object_or_404(Compute, pk=compute_id)
    try:
        conn = wvmConnect(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )

        disk_device_types = conn.get_disk_device_types(arch, machine)

        if disk in disk_device_types:
            if disk == 'disk':
                data['bus'] = sorted(disk_device_types)
            elif disk == 'cdrom':
                data['bus'] = ['ide', 'sata', 'scsi']
            elif disk == 'floppy':
                data['bus'] = ['fdc']
            elif disk == 'lun':
                data['bus'] = ['scsi']
    except libvirtError:
        pass

    return HttpResponse(json.dumps(data))


def get_compute_machine_types(request, compute_id, arch):
    """
    :param request:
    :param compute_id:
    :param arch:
    :return:
    """
    data = dict()
    try:
        compute = get_object_or_404(Compute, pk=compute_id)
        conn = wvmConnect(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        data['machines'] = conn.get_machine_types(arch)
    except libvirtError:
        pass

    return HttpResponse(json.dumps(data))


def get_compute_video_models(request, compute_id, arch, machine):
    """
    :param request:
    :param compute_id:
    :param arch:
    :param machine:
    :return:
    """
    data = dict()
    try:
        compute = get_object_or_404(Compute, pk=compute_id)
        conn = wvmConnect(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        data['videos'] = conn.get_video_models(arch, machine)
    except libvirtError:
        pass

    return HttpResponse(json.dumps(data))


def get_dom_capabilities(request, compute_id, arch, machine):
    """
    :param request:
    :param compute_id:
    :param arch:
    :param machine:
    :return:
    """
    data = dict()
    try:
        compute = get_object_or_404(Compute, pk=compute_id)
        conn = wvmConnect(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        data['videos'] = conn.get_disk_device_types(arch, machine)
        data['bus'] = conn.get_disk_device_types(arch, machine)
    except libvirtError:
        pass

    return HttpResponse(json.dumps(data))
