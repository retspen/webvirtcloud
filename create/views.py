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
from webvirtcloud.settings import QEMU_CONSOLE_LISTEN_ADDRESSES
from webvirtcloud.settings import INSTANCE_VOLUME_DEFAULT_CACHE
from webvirtcloud.settings import INSTANCE_VOLUME_DEFAULT_BUS
from django.contrib import messages
from logs.views import addlogmsg


@login_required
def create_instance(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    conn = None
    error_messages = []
    storages = []
    networks = []
    meta_prealloc = False
    compute = get_object_or_404(Compute, pk=compute_id)
    flavors = Flavor.objects.filter().order_by('id')

    try:
        conn = wvmCreate(compute.hostname,
                         compute.login,
                         compute.password,
                         compute.type)

        instances = conn.get_instances()
        videos = conn.get_video_models()
        cache_modes = sorted(conn.get_cache_modes().items())
        default_cache = INSTANCE_VOLUME_DEFAULT_CACHE
        listener_addr = QEMU_CONSOLE_LISTEN_ADDRESSES
        mac_auto = util.randomMAC()
        disk_devices = conn.get_disk_device_types()
        disk_buses = conn.get_disk_bus_types()
        default_bus = INSTANCE_VOLUME_DEFAULT_BUS
        networks = sorted(conn.get_networks())
        nwfilters = conn.get_nwfilters()
        storages = sorted(conn.get_storages(only_actives=True))
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
                xml = request.POST.get('dom_xml', '')
                try:
                    name = util.get_xml_path(xml, '/domain/name')
                except util.etree.Error as err:
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
                volume_list = []

                clone_path = ""
                form = NewVMForm(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    if data['meta_prealloc']:
                        meta_prealloc = True
                    if instances:
                        if data['name'] in instances:
                            msg = _("A virtual machine with this name already exists")
                            error_messages.append(msg)
                        if Instance.objects.filter(name__exact=data['name']):
                            messages.warning(request, _("There is an instance with same name. Are you sure?"))
                    if not error_messages:
                        if data['hdd_size']:
                            if not data['mac']:
                                error_msg = _("No Virtual Machine MAC has been entered")
                                error_messages.append(error_msg)
                            else:
                                try:
                                    path = conn.create_volume(data['storage'], data['name'], data['hdd_size'],
                                                              metadata=meta_prealloc)
                                    volume = dict()
                                    volume['path'] = path
                                    volume['type'] = conn.get_volume_type(path)
                                    volume['device'] = 'disk'
                                    volume['bus'] = 'virtio'
                                    volume_list.append(volume)
                                except libvirtError as lib_err:
                                    error_messages.append(lib_err.message)
                        elif data['template']:
                            templ_path = conn.get_volume_path(data['template'])
                            dest_vol = conn.get_volume_path(data["name"] + ".img", data['storage'])
                            if dest_vol:
                                error_msg = _("Image has already exist. Please check volumes or change instance name")
                                error_messages.append(error_msg)
                            else:
                                clone_path = conn.clone_from_template(data['name'], templ_path, data['storage'], metadata=meta_prealloc)
                                volume = dict()
                                volume['path'] = clone_path
                                volume['type'] = conn.get_volume_type(clone_path)
                                volume['device'] = 'disk'
                                volume['bus'] = 'virtio'
                                volume_list.append(volume)
                        else:
                            if not data['images']:
                                error_msg = _("First you need to create or select an image")
                                error_messages.append(error_msg)
                            else:
                                for idx, vol in enumerate(data['images'].split(',')):
                                    try:
                                        path = conn.get_volume_path(vol)
                                        volume = dict()
                                        volume['path'] = path
                                        volume['type'] = conn.get_volume_type(path)
                                        volume['device'] = request.POST.get('device' + str(idx), '')
                                        volume['bus'] = request.POST.get('bus' + str(idx), '')
                                        volume_list.append(volume)
                                    except libvirtError as lib_err:
                                        error_messages.append(lib_err.message)
                        if data['cache_mode'] not in conn.get_cache_modes():
                            error_msg = _("Invalid cache mode")
                            error_messages.append(error_msg)
                        if not error_messages:
                            uuid = util.randomUUID()
                            try:
                                conn.create_instance(data['name'], data['memory'], data['vcpu'], data['host_model'],
                                                     uuid, volume_list, data['cache_mode'], data['networks'], data['virtio'],
                                                     data["listener_addr"], data["nwfilter"], data["video"], data["console_pass"],
                                                     data['mac'], data['qemu_ga'])
                                create_instance = Instance(compute_id=compute_id, name=data['name'], uuid=uuid)
                                create_instance.save()
                                msg = _("Instance is created.")
                                messages.success(request, msg)
                                addlogmsg(request.user.username, create_instance.name, msg)
                                return HttpResponseRedirect(reverse('instance', args=[compute_id, data['name']]))
                            except libvirtError as lib_err:
                                if data['hdd_size'] or len(volume_list) > 0:
                                    for vol in volume_list:
                                        conn.delete_volume(vol['path'])
                                error_messages.append(lib_err)
        conn.close()
    return render(request, 'create_instance.html', locals())
