import time
import json
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.shortcuts import render, get_object_or_404
from computes.models import Compute
from instances.models import Instance
from accounts.models import UserInstance
from computes.forms import ComputeAddTcpForm, ComputeAddSshForm, ComputeEditHostForm, ComputeAddTlsForm, ComputeAddSocketForm
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.connection import CONN_SSH, CONN_TCP, CONN_TLS, CONN_SOCKET, connection_manager
from libvirt import libvirtError


def computes(request):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    def get_hosts_status(computes):
        """
        Function return all hosts all vds on host
        """
        compute_data = []
        for compute in computes:
            compute_data.append({'id': compute.id,
                                 'name': compute.name,
                                 'hostname': compute.hostname,
                                 'status': connection_manager.host_is_up(compute.type, compute.hostname),
                                 'type': compute.type,
                                 'login': compute.login,
                                 'password': compute.password,
                                 'gstfsd_key': compute.gstfsd_key
                                 })
        return compute_data

    error_messages = []
    computes = Compute.objects.filter()
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
        if 'host_tcp_add' in request.POST:
            form = ComputeAddTcpForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                new_tcp_host = Compute(name=data['name'],
                                       hostname=data['hostname'],
                                       type=CONN_TCP,
                                       login=data['login'],
                                       password=data['password'],
                                       gstfsd_key=data['gstfsd_key'])
                new_tcp_host.save()
                return HttpResponseRedirect(request.get_full_path())
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
        if 'host_ssh_add' in request.POST:
            form = ComputeAddSshForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                new_ssh_host = Compute(name=data['name'],
                                       hostname=data['hostname'],
                                       type=CONN_SSH,
                                       login=data['login'],
                                       gstfsd_key=data['gstfsd_key'])
                new_ssh_host.save()
                return HttpResponseRedirect(request.get_full_path())
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
        if 'host_tls_add' in request.POST:
            form = ComputeAddTlsForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                new_tls_host = Compute(name=data['name'],
                                       hostname=data['hostname'],
                                       type=CONN_TLS,
                                       login=data['login'],
                                       password=data['password'],
                                       gstfsd_key=data['gstfsd_key'])
                new_tls_host.save()
                return HttpResponseRedirect(request.get_full_path())
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
        if 'host_socket_add' in request.POST:
            form = ComputeAddSocketForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                new_socket_host = Compute(name=data['name'],
                                          hostname='localhost',
                                          type=CONN_SOCKET,
                                          login='',
                                          password='',
                                          gstfsd_key=data['gstfsd_key'])
                new_socket_host.save()
                return HttpResponseRedirect(request.get_full_path())
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
        if 'host_edit' in request.POST:
            form = ComputeEditHostForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                compute_edit = Compute.objects.get(id=data['host_id'])
                compute_edit.name = data['name']
                compute_edit.hostname = data['hostname']
                compute_edit.login = data['login']
                compute_edit.password = data['password']
                compute_edit.gstfsd_key = data['gstfsd_key']
                compute_edit.save()
                return HttpResponseRedirect(request.get_full_path())
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
    return render(request, 'computes.html', locals())


def overview(request, compute_id):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmHostDetails(compute.hostname,
                              compute.login,
                              compute.password,
                              compute.type)
        hostname, host_arch, host_memory, logical_cpu, model_cpu, uri_conn = conn.get_node_info()
        hypervisor = conn.hypervisor_type()
        mem_usage = conn.get_memory_usage()
        conn.close()
    except libvirtError as lib_err:
        error_messages.append(lib_err)

    return render(request, 'overview.html', locals())


def compute_graph(request, compute_id):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('login'))

    points = 5
    datasets = {}
    cookies = {}
    compute = get_object_or_404(Compute, pk=compute_id)
    curent_time = time.strftime("%H:%M:%S")

    try:
        conn = wvmHostDetails(compute.hostname,
                              compute.login,
                              compute.password,
                              compute.type)
        cpu_usage = conn.get_cpu_usage()
        mem_usage = conn.get_memory_usage()
        conn.close()
    except libvirtError:
        cpu_usage = 0
        mem_usage = 0

    try:
        cookies['cpu'] = request.COOKIES['cpu']
        cookies['mem'] = request.COOKIES['mem']
        cookies['timer'] = request.COOKIES['timer']
    except KeyError:
        cookies['cpu'] = None
        cookies['mem'] = None

    if not cookies['cpu'] or not cookies['mem']:
        datasets['cpu'] = [0] * points
        datasets['mem'] = [0] * points
        datasets['timer'] = [0] * points
    else:
        datasets['cpu'] = eval(cookies['cpu'])
        datasets['mem'] = eval(cookies['mem'])
        datasets['timer'] = eval(cookies['timer'])

    datasets['timer'].append(curent_time)
    datasets['cpu'].append(int(cpu_usage['usage']))
    datasets['mem'].append(int(mem_usage['usage']) / 1048576)

    if len(datasets['timer']) > points:
        datasets['timer'].pop(0)
    if len(datasets['cpu']) > points:
        datasets['cpu'].pop(0)
    if len(datasets['mem']) > points:
        datasets['mem'].pop(0)

    data = json.dumps({'cpudata': datasets['cpu'], 'memdata': datasets['mem'], 'timeline': datasets['timer']})
    response = HttpResponse()
    response['Content-Type'] = "text/javascript"
    response.cookies['cpu'] = datasets['cpu']
    response.cookies['timer'] = datasets['timer']
    response.cookies['mem'] = datasets['mem']
    response.write(data)
    return response
