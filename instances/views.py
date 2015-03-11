from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.shortcuts import render
from computes.models import Compute
from instances.models import Instance
from users.models import UserInstance
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.connection import connection_manager
from libvirt import libvirtError


def index(request):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('login'))
    else:
        return HttpResponseRedirect(reverse('instances'))


def instances(request):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    error_messages = []
    all_host_vms = {}
    all_user_vms = {}
    computes = Compute.objects.all()

    if not request.user.is_superuser:
        user_instances = UserInstance.objects.all()
        for usr_inst in user_instances:
            if connection_manager.host_is_up(usr_inst.instance.compute.type,
                                             usr_inst.instance.compute.hostname):
                conn = wvmHostDetails(usr_inst.instance.compute,
                                      usr_inst.instance.compute.login,
                                      usr_inst.instance.compute.password,
                                      usr_inst.instance.compute.type)
                all_user_vms[usr_inst] = conn.get_user_instances(usr_inst.instance.name)
                all_user_vms[usr_inst].update({'compute_id': usr_inst.instance.compute.id})
    else:
        for comp in computes:
            if connection_manager.host_is_up(comp.type, comp.hostname):
                try:
                    conn = wvmHostDetails(comp, comp.login, comp.password, comp.type)
                    all_host_vms[comp.id, comp.name] = conn.get_host_instances()
                    for vm, info in conn.get_host_instances().items():
                        try:
                            check_uuid = Instance.objects.get(compute_id=comp.id, name=vm)
                            if check_uuid.uuid != info['uuid']:
                                check_uuid.save()
                        except Instance.DoesNotExist:
                            check_uuid = Instance(compute_id=comp.id, name=vm, uuid=info['uuid'])
                            check_uuid.save()
                    conn.close()
                except libvirtError as lib_err:
                    error_messages.append(lib_err)

    if request.method == 'POST':
        name = request.POST.get('name', '')
        compute_id = request.POST.get('compute_id', '')
        compute = Compute.objects.get(id=compute_id)
        try:
            conn = wvmInstances(compute.hostname,
                                compute.login,
                                compute.password,
                                compute.type)
            if 'start' in request.POST:
                conn.start(name)
                return HttpResponseRedirect(request.get_full_path())
            if 'destroy' in request.POST:
                conn.force_shutdown(name)
                return HttpResponseRedirect(request.get_full_path())
            if 'suspend' in request.POST:
                conn.suspend(name)
                return HttpResponseRedirect(request.get_full_path())
            if 'resume' in request.POST:
                conn.resume(name)
                return HttpResponseRedirect(request.get_full_path())
        except libvirtError as lib_err:
            error_messages.append(lib_err)

    return render(request, 'instances.html', locals())


def instance(request, comptes_id, vname):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    return render(request, 'instance.html', locals())