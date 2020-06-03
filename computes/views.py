import json

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.urls import reverse
from django.utils import timezone
from libvirt import libvirtError

from accounts.models import UserInstance
from admin.decorators import superuser_only
from computes.forms import (ComputeEditHostForm, SocketComputeForm, SshComputeForm, TcpComputeForm, TlsComputeForm)
from computes.models import Compute
from instances.models import Instance
from vrtManager.connection import (CONN_SOCKET, CONN_SSH, CONN_TCP, CONN_TLS, connection_manager, wvmConnect)
from vrtManager.hostdetails import wvmHostDetails


@superuser_only
def computes(request):
    """
    :param request:
    :return:
    """
    def get_hosts_status(computes):
        """
        Function return all hosts all vds on host
        """
        compute_data = []
        for compute in computes:
            compute_data.append({
                'id': compute.id,
                'name': compute.name,
                'hostname': compute.hostname,
                'status': connection_manager.host_is_up(compute.type, compute.hostname),
                'type': compute.type,
                'login': compute.login,
                'password': compute.password,
                'details': compute.details
            })
        return compute_data

    error_messages = []
    computes = Compute.objects.filter().order_by('name')
    computes_info = get_hosts_status(computes)

    if request.method == 'POST':
        if 'host_del' in request.POST:
            compute_id = request.POST.get('host_id', '')
            try:
                del_user_inst_on_host = UserInstance.objects.filter(instance__compute_id=compute_id)
                del_user_inst_on_host.delete()
            finally:
                try:
                    del_inst_on_host = Instance.objects.filter(compute_id=compute_id)
                    del_inst_on_host.delete()
                finally:
                    del_host = Compute.objects.get(id=compute_id)
                    del_host.delete()
            return HttpResponseRedirect(request.get_full_path())
        if 'host_edit' in request.POST:
            form = ComputeEditHostForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                compute_edit = Compute.objects.get(id=data['host_id'])
                compute_edit.name = data['name']
                compute_edit.hostname = data['hostname']
                compute_edit.login = data['login']
                compute_edit.password = data['password']
                compute_edit.details = data['details']
                compute_edit.save()
                return HttpResponseRedirect(request.get_full_path())
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
    return render(request, 'computes.html', locals())


@superuser_only
def overview(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
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
    except libvirtError as lib_err:
        error_messages.append(lib_err)

    return render(request, 'overview.html', locals())


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


@superuser_only
def add_host(request, FormClass):
    form = FormClass(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect(reverse('computes'))

    return render(request, 'computes/form.html', {'form': form})
