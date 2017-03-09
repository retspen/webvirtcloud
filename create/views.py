from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect
from django.utils.translation import ugettext_lazy as _
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from computes.models import Compute
from create.models import Flavor
from create.forms import FlavorAddForm, NewVMForm
from instances.models import Instance
from vrtManager.create import wvmCreate
from vrtManager import util
from libvirt import libvirtError


@login_required
def create_instance(request, compute_id):
    """
    :param request:
    :return:
    """

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    conn = None
    error_messages = []
    storages = []
    networks = []
    meta_prealloc = False
    computes = Compute.objects.all()
    compute = get_object_or_404(Compute, pk=compute_id)
    flavors = Flavor.objects.filter().order_by('id')

    try:
        conn = wvmCreate(compute.hostname,
                         compute.login,
                         compute.password,
                         compute.type)

        storages = sorted(conn.get_storages())
        networks = sorted(conn.get_networks())
        instances = conn.get_instances()
        get_images = sorted(conn.get_storages_images())
        cache_modes = sorted(conn.get_cache_modes().items())
        mac_auto = util.randomMAC()
    except libvirtError as lib_err:
        error_messages.append(lib_err)

    if conn:
        if not storages:
            msg = _("You haven't defined any storage pools")
            error_messages.append(msg)
        if not networks:
            msg = _("You haven't defined any network pools")
            error_messages.append(msg)

        if request.method == 'POST':
            if 'create_flavor' in request.POST:
                form = FlavorAddForm(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    create_flavor = Flavor(label=data['label'],
                                           vcpu=data['vcpu'],
                                           memory=data['memory'],
                                           disk=data['disk'])
                    create_flavor.save()
                    return HttpResponseRedirect(request.get_full_path())
            if 'delete_flavor' in request.POST:
                flavor_id = request.POST.get('flavor', '')
                delete_flavor = Flavor.objects.get(id=flavor_id)
                delete_flavor.delete()
                return HttpResponseRedirect(request.get_full_path())
            if 'create_xml' in request.POST:
                xml = request.POST.get('from_xml', '')
                try:
                    name = util.get_xml_path(xml, '/domain/name')
                except util.libxml2.parserError:
                    name = None
                if name in instances:
                    error_msg = _("A virtual machine with this name already exists")
                    error_messages.append(error_msg)
                else:
                    try:
                        conn._defineXML(xml)
                        return HttpResponseRedirect(reverse('instance', args=[compute_id, name]))
                    except libvirtError as lib_err:
                        error_messages.append(lib_err.message)
            if 'create' in request.POST:
                volumes = {}
                form = NewVMForm(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    if data['meta_prealloc']:
                        meta_prealloc = True
                    if instances:
                        if data['name'] in instances:
                            msg = _("A virtual machine with this name already exists")
                            error_messages.append(msg)
                    if not error_messages:
                        if data['hdd_size']:
                            if not data['mac']:
                                error_msg = _("No Virtual Machine MAC has been entered")
                                error_messages.append(error_msg)
                            else:
                                try:
                                    path = conn.create_volume(data['storage'], data['name'], data['hdd_size'],
                                                              metadata=meta_prealloc)
                                    volumes[path] = conn.get_volume_type(path)
                                except libvirtError as lib_err:
                                    error_messages.append(lib_err.message)
                        elif data['template']:
                            templ_path = conn.get_volume_path(data['template'])
                            clone_path = conn.clone_from_template(data['name'], templ_path, metadata=meta_prealloc)
                            volumes[clone_path] = conn.get_volume_type(clone_path)
                        else:
                            if not data['images']:
                                error_msg = _("First you need to create or select an image")
                                error_messages.append(error_msg)
                            else:
                                for vol in data['images'].split(','):
                                    try:
                                        path = conn.get_volume_path(vol)
                                        volumes[path] = conn.get_volume_type(path)
                                    except libvirtError as lib_err:
                                        error_messages.append(lib_err.message)
                        if data['cache_mode'] not in conn.get_cache_modes():
                            error_msg = _("Invalid cache mode")
                            error_messages.append(error_msg)
                        if not error_messages:
                            uuid = util.randomUUID()
                            try:
                                conn.create_instance(data['name'], data['memory'], data['vcpu'], data['host_model'],
                                                     uuid, volumes, data['cache_mode'], data['networks'], data['virtio'],
                                                     data['mac'])
                                create_instance = Instance(compute_id=compute_id, name=data['name'], uuid=uuid)
                                create_instance.save()
                                return HttpResponseRedirect(reverse('instance', args=[compute_id, data['name']]))
                            except libvirtError as lib_err:
                                if data['hdd_size']:
                                    conn.delete_volume(volumes.keys()[0])
                                error_messages.append(lib_err)
        conn.close()

    return render(request, 'create_instance.html', locals())
