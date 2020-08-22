import crypt
import json
import os
import random
import re
import socket
import string
import time
from bisect import insort
from collections import OrderedDict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import User
from django.http import (Http404, HttpResponse, JsonResponse)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from libvirt import (VIR_DOMAIN_UNDEFINE_KEEP_NVRAM, VIR_DOMAIN_UNDEFINE_NVRAM, VIR_DOMAIN_XML_SECURE, libvirtError)

from accounts.models import UserInstance, UserSSHKey
from admin.decorators import superuser_only
from appsettings.models import AppSettings
from appsettings.settings import app_settings
from computes.models import Compute
from instances.models import Instance
from logs.views import addlogmsg
from vrtManager import util
from vrtManager.connection import connection_manager
from vrtManager.create import wvmCreate
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.storage import wvmStorage
from vrtManager.util import randomPasswd

from . import utils
from .forms import ConsoleForm, FlavorForm, NewVMForm
from .models import Flavor


def index(request):
    instances = None

    computes = Compute.objects.all().order_by("name").prefetch_related('instance_set').prefetch_related(
        'instance_set__userinstance_set')
    for compute in computes:
        utils.refr(compute)

    if request.user.is_superuser:
        instances = Instance.objects.all().prefetch_related('userinstance_set')
    else:
        instances = Instance.objects.filter(userinstance__user=request.user).prefetch_related('userinstance_set')

    return render(request, 'allinstances.html', {'computes': computes, 'instances': instances})


def instance(request, pk):
    instance: Instance = get_object_or_404(Instance, pk=pk)
    compute: Compute = instance.compute
    computes = Compute.objects.all().order_by('name')
    computes_count = computes.count()
    users = User.objects.all().order_by('username')
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)
    keymaps = settings.QEMU_KEYMAPS
    console_types = AppSettings.objects.get(key="QEMU_CONSOLE_DEFAULT_TYPE").choices_as_list()
    #
    console_form = ConsoleForm(
        initial={
            'type': instance.console_type,
            'listen_on': instance.console_listen_address,
            'password': instance.console_passwd,
            'keymap': instance.console_keymap,
        })
    #
    console_listen_addresses = settings.QEMU_CONSOLE_LISTEN_ADDRESSES
    bottom_bar = app_settings.VIEW_INSTANCE_DETAIL_BOTTOM_BAR
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    try:
        userinstance = UserInstance.objects.get(instance__compute_id=compute.id,
                                                instance__name=instance.name,
                                                user__id=request.user.id)
    except UserInstance.DoesNotExist:
        userinstance = None

    if not request.user.is_superuser:
        if not userinstance:
            return redirect(reverse('index'))

    if len(instance.media) != 0:
        media_iso = sorted(instance.proxy.get_iso_media())
    else:
        media_iso = []

    memory_range = [256, 512, 768, 1024, 2048, 3072, 4096, 6144, 8192, 16384]
    if instance.memory not in memory_range:
        insort(memory_range, instance.memory)
    if instance.cur_memory not in memory_range:
        insort(memory_range, instance.cur_memory)
    clone_free_names = utils.get_clone_free_names()
    user_quota_msg = utils.check_user_quota(request.user, 0, 0, 0, 0)

    default_bus = app_settings.INSTANCE_VOLUME_DEFAULT_BUS
    default_io = app_settings.INSTANCE_VOLUME_DEFAULT_IO
    default_discard = app_settings.INSTANCE_VOLUME_DEFAULT_DISCARD
    default_zeroes = app_settings.INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES
    default_cache = app_settings.INSTANCE_VOLUME_DEFAULT_CACHE
    default_format = app_settings.INSTANCE_VOLUME_DEFAULT_FORMAT
    # default_disk_owner_uid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
    # default_disk_owner_gid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)

    # clone_instance_auto_name = app_settings.CLONE_INSTANCE_AUTO_NAME

    # try:
    #     instance = Instance.objects.get(compute=compute, name=vname)
    #     if instance.uuid != uuid:
    #         instance.uuid = uuid
    #         instance.save()
    #         msg = _(f"Fixing UUID {uuid}")
    #         addlogmsg(request.user.username, instance.name, msg)
    # except Instance.DoesNotExist:
    #     instance = Instance(compute=compute, name=vname, uuid=uuid)
    #     instance.save()
    #     msg = _("Instance does not exist: Creating new instance")
    #     addlogmsg(request.user.username, instance.name, msg)

    # userinstances = UserInstance.objects.filter(instance=instance).order_by('user__username')
    userinstances = instance.userinstance_set.order_by('user__username')
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template

    # Host resources
    vcpu_host = len(instance.vcpu_range)
    memory_host = instance.proxy.get_max_memory()
    bus_host = instance.proxy.get_disk_bus_types(instance.arch, instance.machine)
    # videos_host = instance.proxy.get_video_models(instance.arch, instance.machine)
    networks_host = sorted(instance.proxy.get_networks())
    nwfilters_host = instance.proxy.get_nwfilters()
    storages_host = sorted(instance.proxy.get_storages(True))
    net_models_host = instance.proxy.get_network_models()

    try:
        interfaces_host = sorted(instance.proxy.get_ifaces())
    except Exception as e:
        addlogmsg(request.user.username, instance.name, e)
        messages.error(request, e)

    return render(request, 'instance.html', locals())


def status(request, pk):
    instance = get_instance(request.user, pk)
    return JsonResponse({'status': instance.proxy.get_status()})


def stats(request, pk):
    instance = get_instance(request.user, pk)
    json_blk = []
    json_net = []

    # TODO: stats are inaccurate
    cpu_usage = instance.proxy.cpu_usage()
    mem_usage = instance.proxy.mem_usage()
    blk_usage = instance.proxy.disk_usage()
    net_usage = instance.proxy.net_usage()

    current_time = time.strftime("%H:%M:%S")
    for blk in blk_usage:
        json_blk.append({'dev': blk['dev'], 'data': [int(blk['rd']) / 1048576, int(blk['wr']) / 1048576]})

    for net in net_usage:
        json_net.append({'dev': net['dev'], 'data': [int(net['rx']) / 1048576, int(net['tx']) / 1048576]})

    return JsonResponse({
        'cpudata': int(cpu_usage['cpu']),
        'memdata': mem_usage,
        'blkdata': json_blk,
        'netdata': json_net,
        'timeline': current_time,
    })


def guess_mac_address(request, vname):
    data = {'vname': vname}
    mac = utils.get_dhcp_mac_address(vname)
    if not mac:
        mac = utils.get_random_mac_address()
    data['mac'] = mac
    return HttpResponse(json.dumps(data))


def random_mac_address(request):
    data = dict()
    data['mac'] = utils.get_random_mac_address()
    return HttpResponse(json.dumps(data))


def guess_clone_name(request):
    dhcp_file = '/srv/webvirtcloud/dhcpd.conf'
    prefix = app_settings.CLONE_INSTANCE_DEFAULT_PREFIX
    if os.path.isfile(dhcp_file):
        instance_names = [i.name for i in Instance.objects.filter(name__startswith=prefix)]
        with open(dhcp_file, 'r') as f:
            for line in f:
                line = line.strip()
                if f"host {prefix}" in line:
                    fqdn = line.split(' ')[1]
                    hostname = fqdn.split('.')[0]
                    if hostname.startswith(prefix) and hostname not in instance_names:
                        return HttpResponse(json.dumps({'name': hostname}))
    return HttpResponse(json.dumps({}))


def check_instance(request, vname):
    instance = Instance.objects.filter(name=vname)
    data = {'vname': vname, 'exists': False}
    if instance:
        data['exists'] = True
    return HttpResponse(json.dumps(data))


def sshkeys(request, vname):
    """
    :param request:
    :param vname:
    :return:
    """

    instance_keys = []
    userinstances = UserInstance.objects.filter(instance__name=vname)

    for ui in userinstances:
        keys = UserSSHKey.objects.filter(user=ui.user)
        for k in keys:
            instance_keys.append(k.keypublic)
    if request.GET.get('plain', ''):
        response = '\n'.join(instance_keys)
        response += '\n'
    else:
        response = json.dumps(instance_keys)
    return HttpResponse(response)


def get_instance(user, pk):
    '''
    Check that instance is available for user, if not raise 404
    '''
    instance = Instance.objects.get(pk=pk)
    user_instances = user.userinstance_set.all().values_list('instance', flat=True)

    if user.is_superuser or instance.id in user_instances:
        return instance
    else:
        raise Http404()


def poweron(request, pk):
    instance = get_instance(request.user, pk)
    if instance.is_template:
        messages.warning(request, _("Templates cannot be started."))
    else:
        instance.proxy.start()
        addlogmsg(request.user.username, instance.name, _("Power On"))

    return redirect(request.META.get('HTTP_REFERER'))


def powercycle(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.force_shutdown()
    instance.proxy.start()
    addlogmsg(request.user.username, instance.name, _("Power Cycle"))
    return redirect(request.META.get('HTTP_REFERER'))


def poweroff(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.shutdown()
    addlogmsg(request.user.username, instance.name, _("Power Off"))

    return redirect(request.META.get('HTTP_REFERER'))


@superuser_only
def suspend(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.suspend()
    addlogmsg(request.user.username, instance.name, _("Suspend"))
    return redirect(request.META.get('HTTP_REFERER'))


@superuser_only
def resume(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.resume()
    addlogmsg(request.user.username, instance.name, _("Resume"))
    return redirect(request.META.get('HTTP_REFERER'))


def force_off(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.force_shutdown()
    addlogmsg(request.user.username, instance.name, _("Force Off"))
    return redirect(request.META.get('HTTP_REFERER'))


def destroy(request, pk):
    instance = get_instance(request.user, pk)
    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except:
        userinstance = UserInstance(is_delete=request.user.is_superuser)

    if request.method == 'POST' and userinstance.is_delete:
        if instance.proxy.get_status() == 1:
            instance.proxy.force_shutdown()

        if request.POST.get('delete_disk', ''):
            snapshots = sorted(instance.proxy.get_snapshot(), reverse=True, key=lambda k: k['date'])
            for snapshot in snapshots:
                instance.proxy.snapshot_delete(snapshot['name'])
            instance.proxy.delete_all_disks()

        if request.POST.get('delete_nvram', ''):
            instance.proxy.delete(VIR_DOMAIN_UNDEFINE_NVRAM)
        else:
            instance.proxy.delete(VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)

        instance.delete()
        addlogmsg(request.user, instance.name, _("Destroy"))
        return redirect(reverse('instances:index'))

    return render(
        request,
        'instances/destroy_instance_form.html',
        {
            'instance': instance,
            'userinstance': userinstance,
        },
    )


@superuser_only
def migrate(request, pk):
    instance = get_instance(request.user, pk)

    compute_id = request.POST.get('compute_id', '')
    live = request.POST.get('live_migrate', False)
    unsafe = request.POST.get('unsafe_migrate', False)
    xml_del = request.POST.get('xml_delete', False)
    offline = request.POST.get('offline_migrate', False)
    autoconverge = request.POST.get('autoconverge', False)
    compress = request.POST.get('compress', False)
    postcopy = request.POST.get('postcopy', False)

    new_compute = Compute.objects.get(id=compute_id)

    try:
        utils.migrate_instance(new_compute, instance, request.user, live, unsafe, xml_del, offline)
    except libvirtError as err:
        messages.error(request, err)

    msg = _(f"Migrate to {new_compute.hostname}")
    addlogmsg(request.user, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER'))


def set_root_pass(request, pk):
    instance = get_instance(request.user, pk)

    if request.method == 'POST':
        passwd = request.POST.get('passwd', None)
        if passwd:
            passwd_hash = crypt.crypt(passwd, '$6$kgPoiREy')
            data = {'action': 'password', 'passwd': passwd_hash, 'vname': instance.name}

            if instance.proxy.get_status() == 5:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((instance.compute.hostname, 16510))
                s.send(bytes(json.dumps(data).encode()))
                d = s.recv(1024).strip()
                result = json.loads(d)
                s.close()
                if result['return'] == 'success':
                    msg = _("Reset root password")
                    addlogmsg(request.user.username, instance.name, msg)
                    messages.success(request, msg)
                else:
                    messages.error(request, result['message'])
            else:
                msg = _("Please shutdown down your instance and then try again")
                messages.error(request, msg)
    return redirect(reverse('instances:instance', args=[instance.id]) + '#access')


def add_public_key(request, pk):
    instance = get_instance(request.user, pk)
    if request.method == 'POST':
        sshkeyid = request.POST.get('sshkeyid', '')
        publickey = UserSSHKey.objects.get(id=sshkeyid)
        data = {'action': 'publickey', 'key': publickey.keypublic, 'vname': instance.name}

        if instance.proxy.get_status() == 5:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((instance.compute.hostname, 16510))
            s.send(json.dumps(data))
            result = json.loads(s.recv(1024))
            s.close()
            msg = _(f"Installed new SSH public key {publickey.keyname}")
            addlogmsg(request.user.username, instance.name, msg)

            if result['return'] == 'success':
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        else:
            msg = _("Please shutdown down your instance and then try again")
            messages.error(request, msg)
    return redirect(reverse('instances:instance', args=[instance.id]) + '#access')


def resizevm_cpu(request, pk):
    instance = get_instance(request.user, pk)
    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except:
        userinstance = UserInstance(is_change=False)
    vcpu = instance.proxy.get_vcpu()
    if request.method == 'POST':
        if request.user.is_superuser or request.user.is_staff or userinstance.is_change:
            new_vcpu = request.POST.get('vcpu', '')
            new_cur_vcpu = request.POST.get('cur_vcpu', '')

            quota_msg = utils.check_user_quota(request.user, 0, int(new_vcpu) - vcpu, 0, 0)
            if not request.user.is_superuser and quota_msg:
                msg = _(f"User {quota_msg} quota reached, cannot resize CPU of '{instance.name}'!")
                messages.error(request, msg)
            else:
                cur_vcpu = new_cur_vcpu
                vcpu = new_vcpu
                instance.proxy.resize_cpu(cur_vcpu, vcpu)
                msg = _("Resize CPU")
                addlogmsg(request.user.username, instance.name, msg)
                messages.success(request, msg)
    return redirect(reverse('instances:instance', args=[instance.id]) + '#resize')


def resize_memory(request, pk):
    instance = get_instance(request.user, pk)
    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except:
        userinstance = UserInstance(is_change=False)

    memory = instance.proxy.get_memory()
    cur_memory = instance.proxy.get_cur_memory()

    if request.method == 'POST':
        if request.user.is_superuser or request.user.is_staff or userinstance.is_change:
            new_memory = request.POST.get('memory', '')
            new_memory_custom = request.POST.get('memory_custom', '')
            if new_memory_custom:
                new_memory = new_memory_custom
            new_cur_memory = request.POST.get('cur_memory', '')
            new_cur_memory_custom = request.POST.get('cur_memory_custom', '')
            if new_cur_memory_custom:
                new_cur_memory = new_cur_memory_custom
            quota_msg = utils.check_user_quota(request.user, 0, 0, int(new_memory) - memory, 0)
            if not request.user.is_superuser and quota_msg:
                msg = _(f"User {quota_msg} quota reached, cannot resize memory of '{instance.name}'!")
                messages.error(request, msg)
            else:
                cur_memory = new_cur_memory
                memory = new_memory
                instance.proxy.resize_mem(cur_memory, memory)
                msg = _("Resize Memory")
                addlogmsg(request.user.username, instance.name, msg)
                messages.success(request, msg)

    return redirect(reverse('instances:instance', args=[instance.id]) + '#resize')


def resize_disk(request, pk):
    instance = get_instance(request.user, pk)

    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except:
        userinstance = UserInstance(is_change=False)

    disks = instance.proxy.get_disk_devices()

    if request.method == 'POST':
        if request.user.is_superuser or request.user.is_staff or userinstance.is_change:
            disks_new = list()
            for disk in disks:
                # input_disk_size = utils.filesizefstr(request.POST.get('disk_size_' + disk['dev'], ''))
                input_disk_size = int(request.POST.get('disk_size_' + disk['dev'], '0')) * 1073741824
                if input_disk_size > disk['size'] + (64 << 20):
                    disk['size_new'] = input_disk_size
                    disks_new.append(disk)
            disk_sum = sum([disk['size'] >> 30 for disk in disks_new])
            disk_new_sum = sum([disk['size_new'] >> 30 for disk in disks_new])
            quota_msg = utils.check_user_quota(request.user, 0, 0, 0, disk_new_sum - disk_sum)
            if not request.user.is_superuser and quota_msg:
                msg = _(f"User {quota_msg} quota reached, cannot resize disks of '{instance.name}'!")
                messages.error(request, msg)
            else:
                instance.proxy.resize_disk(disks_new)
                msg = _("Disk resize")
                addlogmsg(request.user.username, instance.name, msg)
                messages.success(request, msg)

    return redirect(reverse('instances:instance', args=[instance.id]) + '#resize')


def add_new_vol(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template

    if allow_admin_or_not_template:
        media = instance.proxy.get_media_devices()
        disks = instance.proxy.get_disk_devices()
        conn_create = wvmCreate(
            instance.compute.hostname,
            instance.compute.login,
            instance.compute.password,
            instance.compute.type,
        )
        storage = request.POST.get('storage', '')
        name = request.POST.get('name', '')
        format = request.POST.get('format', app_settings.INSTANCE_VOLUME_DEFAULT_FORMAT)
        size = request.POST.get('size', 0)
        meta_prealloc = True if request.POST.get('meta_prealloc', False) else False
        bus = request.POST.get('bus', app_settings.INSTANCE_VOLUME_DEFAULT_BUS)
        cache = request.POST.get('cache', app_settings.INSTANCE_VOLUME_DEFAULT_CACHE)
        target_dev = utils.get_new_disk_dev(media, disks, bus)

        source = conn_create.create_volume(
            storage,
            name,
            size,
            format,
            meta_prealloc,
            int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID),
            int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID),
        )
        instance.proxy.attach_disk(target_dev, source, target_bus=bus, driver_type=format, cache_mode=cache)
        msg = _(f"Attach new disk {name} ({format})")
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def add_existing_vol(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if allow_admin_or_not_template:
        storage = request.POST.get('selected_storage', '')
        name = request.POST.get('vols', '')
        bus = request.POST.get('bus', app_settings.INSTANCE_VOLUME_DEFAULT_BUS)
        cache = request.POST.get('cache', app_settings.INSTANCE_VOLUME_DEFAULT_CACHE)

        media = instance.proxy.get_media_devices()
        disks = instance.proxy.get_disk_devices()

        conn_create = wvmStorage(
            instance.compute.hostname,
            instance.compute.login,
            instance.compute.password,
            instance.compute.type,
            storage,
        )

        driver_type = conn_create.get_volume_type(name)
        path = conn_create.get_target_path()
        target_dev = utils.get_new_disk_dev(media, disks, bus)
        source = f"{path}/{name}"

        instance.proxy.attach_disk(target_dev, source, target_bus=bus, driver_type=driver_type, cache_mode=cache)
        msg = _(f"Attach Existing disk: {target_dev}")
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def edit_volume(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if 'edit_volume' in request.POST and allow_admin_or_not_template:
        target_dev = request.POST.get('dev', '')

        new_path = request.POST.get('vol_path', '')
        shareable = bool(request.POST.get('vol_shareable', False))
        readonly = bool(request.POST.get('vol_readonly', False))
        disk_type = request.POST.get('vol_type', '')
        new_bus = request.POST.get('vol_bus', '')
        bus = request.POST.get('vol_bus_old', '')
        serial = request.POST.get('vol_serial', '')
        format = request.POST.get('vol_format', '')
        cache = request.POST.get('vol_cache', app_settings.INSTANCE_VOLUME_DEFAULT_CACHE)
        io = request.POST.get('vol_io_mode', app_settings.INSTANCE_VOLUME_DEFAULT_IO)
        discard = request.POST.get('vol_discard_mode', app_settings.INSTANCE_VOLUME_DEFAULT_DISCARD)
        zeroes = request.POST.get('vol_detect_zeroes', app_settings.INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES)
        new_target_dev = utils.get_new_disk_dev(instance.media, instance.disks, new_bus)

        if new_bus != bus:
            instance.proxy.detach_disk(target_dev)
            instance.proxy.attach_disk(
                new_target_dev,
                new_path,
                target_bus=new_bus,
                driver_type=format,
                cache_mode=cache,
                readonly=readonly,
                shareable=shareable,
                serial=serial,
                io_mode=io,
                discard_mode=discard,
                detect_zeroes_mode=zeroes,
            )
        else:
            instance.proxy.edit_disk(
                target_dev,
                new_path,
                readonly,
                shareable,
                new_bus,
                serial,
                format,
                cache,
                io,
                discard,
                zeroes,
            )

        if not instance.proxy.get_status() == 5:
            messages.success(request, _("Volume changes are applied. " + "But it will be activated after shutdown"))
        else:
            messages.success(request, _("Volume is changed successfully."))
        msg = _(f"Edit disk: {target_dev}")
        addlogmsg(request.user.username, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def delete_vol(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if allow_admin_or_not_template:
        storage = request.POST.get('storage', '')
        conn_delete = wvmStorage(
            instance.compute.hostname,
            instance.compute.login,
            instance.compute.password,
            instance.compute.type,
            storage,
        )
        dev = request.POST.get('dev', '')
        path = request.POST.get('path', '')
        name = request.POST.get('name', '')

        msg = _(f"Delete disk: {dev}")
        instance.proxy.detach_disk(dev)
        conn_delete.del_volume(name)

        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def detach_vol(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template

    if allow_admin_or_not_template:
        dev = request.POST.get('dev', '')
        path = request.POST.get('path', '')
        instance.proxy.detach_disk(dev)
        msg = _(f"Detach disk: {dev}")
        addlogmsg(request.user.username, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def add_cdrom(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if allow_admin_or_not_template:
        bus = request.POST.get('bus', 'ide' if instance.machine == 'pc' else 'sata')
        target = utils.get_new_disk_dev(instance.media, instance.disks, bus)
        instance.proxy.attach_disk(target, "", disk_device='cdrom', cache_mode='none', target_bus=bus, readonly=True)
        msg = _(f"Add CD-ROM: {target}")
        addlogmsg(request.user.username, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def detach_cdrom(request, pk, dev):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template

    if allow_admin_or_not_template:
        # dev = request.POST.get('detach_cdrom', '')
        instance.proxy.detach_disk(dev)
        msg = _(f'Detach CD-ROM: {dev}')
        addlogmsg(request.user.username, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def unmount_iso(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if allow_admin_or_not_template:
        image = request.POST.get('path', '')
        dev = request.POST.get('umount_iso', '')
        instance.proxy.umount_iso(dev, image)
        msg = _(f"Mount media: {dev}")
        addlogmsg(request.user.username, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def mount_iso(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if allow_admin_or_not_template:
        image = request.POST.get('media', '')
        dev = request.POST.get('mount_iso', '')
        instance.proxy.mount_iso(dev, image)
        msg = _(f"Umount media: {dev}")
        addlogmsg(request.user.username, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER') + '#disks')


def snapshot(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template

    if allow_admin_or_not_template:
        name = request.POST.get('name', '')
        instance.proxy.create_snapshot(name)
        msg = _(f"New snapshot : {name}")
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#managesnapshot')


def delete_snapshot(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if allow_admin_or_not_template:
        snap_name = request.POST.get('name', '')
        instance.proxy.snapshot_delete(snap_name)
        msg = _(f"Delete snapshot : {snap_name}")
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#managesnapshot')


def revert_snapshot(request, pk):
    instance = get_instance(request.user, pk)
    allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template
    if allow_admin_or_not_template:
        snap_name = request.POST.get('name', '')
        instance.proxy.snapshot_revert(snap_name)
        msg = _("Successful revert snapshot: ")
        msg += snap_name
        messages.success(request, msg)
        msg = _("Revert snapshot")
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#managesnapshot')


@superuser_only
def set_vcpu(request, pk):
    instance = get_instance(request.user, pk)
    id = request.POST.get('id', '')
    enabled = request.POST.get('set_vcpu', '')
    if enabled == 'True':
        instance.proxy.set_vcpu(id, 1)
    else:
        instance.proxy.set_vcpu(id, 0)
    msg = _(f"VCPU {id} is enabled={enabled}")
    messages.success(request, msg)
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#resize')


@superuser_only
def set_vcpu_hotplug(request, pk):
    instance = get_instance(request.user, pk)
    status = request.POST.get('vcpu_hotplug', '')
    # TODO: f strings are not translatable https://code.djangoproject.com/ticket/29174
    msg = _(f"VCPU Hot-plug is enabled={status}")
    instance.proxy.set_vcpu_hotplug(eval(status))
    messages.success(request, msg)
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#resize')


@superuser_only
def set_autostart(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.set_autostart(1)
    msg = _("Set autostart")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#boot_opt')


@superuser_only
def unset_autostart(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.set_autostart(0)
    msg = _("Unset autostart")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#boot_opt')


@superuser_only
def set_bootmenu(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.set_bootmenu(1)
    msg = _("Enable boot menu")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#boot_opt')


@superuser_only
def unset_bootmenu(request, pk):
    instance = get_instance(request.user, pk)
    instance.proxy.set_bootmenu(0)
    msg = _("Disable boot menu")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#boot_opt')


@superuser_only
def set_bootorder(request, pk):
    instance = get_instance(request.user, pk)
    bootorder = request.POST.get('bootorder', '')
    if bootorder:
        order_list = {}
        for idx, val in enumerate(bootorder.split(',')):
            dev_type, dev = val.split(':', 1)
            order_list[idx] = {"type": dev_type, "dev": dev}
        instance.proxy.set_bootorder(order_list)
        msg = _("Set boot order")

        if not instance.proxy.get_status() == 5:
            messages.success(request, _("Boot menu changes applied. " + "But it will be activated after shutdown"))
        else:
            messages.success(request, _("Boot order changed successfully."))
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#boot_opt')


@superuser_only
def change_xml(request, pk):
    instance = get_instance(request.user, pk)
    exit_xml = request.POST.get('inst_xml', '')
    if exit_xml:
        instance.proxy._defineXML(exit_xml)
        msg = _("Edit XML")
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#xmledit')


@superuser_only
def set_guest_agent(request, pk):
    instance = get_instance(request.user, pk)
    status = request.POST.get('guest_agent')
    if status == 'True':
        instance.proxy.add_guest_agent()
    if status == 'False':
        instance.proxy.remove_guest_agent()

    msg = _(f"Set Quest Agent {status}")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#options')


@superuser_only
def set_video_model(request, pk):
    instance = get_instance(request.user, pk)
    video_model = request.POST.get('video_model', 'vga')
    instance.proxy.set_video_model(video_model)
    msg = _("Set Video Model")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#options')


@superuser_only
def change_network(request, pk):
    instance = get_instance(request.user, pk)

    msg = _("Change network")
    network_data = {}

    for post in request.POST:
        if post.startswith('net-source-'):
            (source, source_type) = utils.get_network_tuple(request.POST.get(post))
            network_data[post] = source
            network_data[post + '-type'] = source_type
        elif post.startswith('net-'):
            network_data[post] = request.POST.get(post, '')

    instance.proxy.change_network(network_data)
    addlogmsg(request.user.username, instance.name, msg)
    msg = _("Network Device Config is changed. Please shutdown instance to activate.")
    if instance.proxy.get_status() != 5: messages.success(request, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#network')


@superuser_only
def add_network(request, pk):
    instance = get_instance(request.user, pk)
    msg = _("Add network")
    mac = request.POST.get('add-net-mac')
    nwfilter = request.POST.get('add-net-nwfilter')
    (source, source_type) = utils.get_network_tuple(request.POST.get('add-net-network'))

    instance.proxy.add_network(mac, source, source_type, nwfilter=nwfilter)
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#network')


@superuser_only
def delete_network(request, pk):
    instance = get_instance(request.user, pk)

    msg = _("Delete network")
    mac_address = request.POST.get('delete_network', '')

    instance.proxy.delete_network(mac_address)
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#network')


@superuser_only
def set_link_state(request, pk):
    instance = get_instance(request.user, pk)

    mac_address = request.POST.get('mac', '')
    state = request.POST.get('set_link_state')
    state = 'down' if state == 'up' else 'up'
    instance.proxy.set_link_state(mac_address, state)
    msg = _(f"Set Link State: {state}")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#network')


@superuser_only
def set_qos(request, pk):
    instance = get_instance(request.user, pk)

    qos_dir = request.POST.get('qos_direction', '')
    average = request.POST.get('qos_average') or 0
    peak = request.POST.get('qos_peak') or 0
    burst = request.POST.get('qos_burst') or 0
    keys = request.POST.keys()
    mac_key = [key for key in keys if 'mac' in key]
    if mac_key: mac = request.POST.get(mac_key[0])

    instance.proxy.set_qos(mac, qos_dir, average, peak, burst)
    if instance.proxy.get_status() == 5:
        messages.success(request, _(f"{qos_dir.capitalize()} QoS is set"))
    else:
        messages.success(
            request,
            _(f"{qos_dir.capitalize()} QoS is set. Network XML is changed. \
                Stop and start network to activate new config.")
        )

    return redirect(request.META.get('HTTP_REFERER') + '#network')


@superuser_only
def unset_qos(request, pk):
    instance = get_instance(request.user, pk)
    qos_dir = request.POST.get('qos_direction', '')
    mac = request.POST.get('net-mac')
    instance.proxy.unset_qos(mac, qos_dir)

    if instance.proxy.get_status() == 5:
        messages.success(request, _(f"{qos_dir.capitalize()} QoS is deleted"))
    else:
        messages.success(
            request,
            _(f"{qos_dir.capitalize()} QoS is deleted. Network XML is changed. \
                Stop and start network to activate new config.")
        )
    return redirect(request.META.get('HTTP_REFERER') + '#network')


@superuser_only
def add_owner(request, pk):
    instance = get_instance(request.user, pk)
    user_id = request.POST.get('user_id')

    check_inst = 0

    if app_settings.ALLOW_INSTANCE_MULTIPLE_OWNER == 'False':
        check_inst = UserInstance.objects.filter(instance=instance).count()

    if check_inst > 1:
        messages.error(request, _("Only one owner is allowed and the one already added"))
    else:
        add_user_inst = UserInstance(instance=instance, user_id=user_id)
        add_user_inst.save()
        user = User.objects.get(id=user_id)
        msg = _("Added owner %(user)s") % {'user': user}
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#users')


@superuser_only
def del_owner(request, pk):
    instance = get_instance(request.user, pk)
    userinstance_id = int(request.POST.get('userinstance', ''))
    userinstance = UserInstance.objects.get(pk=userinstance_id)
    userinstance.delete()
    msg = _(f"Deleted owner {userinstance_id}")
    addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#users')


@permission_required('instances.clone_instances')
def clone(request, pk):
    instance = get_instance(request.user, pk)

    clone_data = dict()
    clone_data['name'] = request.POST.get('name', '')

    disk_sum = sum([disk['size'] >> 30 for disk in instance.disks])
    quota_msg = utils.check_user_quota(request.user, 1, instance.vcpu, instance.memory, disk_sum)
    check_instance = Instance.objects.filter(name=clone_data['name'])

    clone_data['disk_owner_uid'] = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
    clone_data['disk_owner_gid'] = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)

    for post in request.POST:
        clone_data[post] = request.POST.get(post, '').strip()

    if app_settings.CLONE_INSTANCE_AUTO_NAME == 'True' and not clone_data['name']:
        auto_vname = utils.get_clone_free_names()[0]
        clone_data['name'] = auto_vname
        clone_data['clone-net-mac-0'] = utils.get_dhcp_mac_address(auto_vname)
        for disk in instance.disks:
            disk_dev = f"disk-{disk['dev']}"
            disk_name = utils.get_clone_disk_name(disk, instance.name, auto_vname)
            clone_data[disk_dev] = disk_name

    if not request.user.is_superuser and quota_msg:
        msg = _(f"User '{quota_msg}' quota reached, cannot create '{clone_data['name']}'!")
        messages.error(request, msg)
    elif check_instance:
        msg = _(f"Instance '{clone_data['name']}' already exists!")
        messages.error(request, msg)
    elif not re.match(r'^[a-zA-Z0-9-]+$', clone_data['name']):
        msg = _(f"Instance name '{clone_data['name']}' contains invalid characters!")
        messages.error(request, msg)
    elif not re.match(r'^([0-9A-F]{2})(:?[0-9A-F]{2}){5}$', clone_data['clone-net-mac-0'], re.IGNORECASE):
        msg = _(f"Instance MAC '{clone_data['clone-net-mac-0']}' invalid format!")
        messages.error(request, msg)
    else:
        new_instance = Instance(compute=instance.compute, name=clone_data['name'])
        try:
            new_uuid = instance.proxy.clone_instance(clone_data)
            new_instance.uuid = new_uuid
            new_instance.save()
            user_instance = UserInstance(instance_id=new_instance.id, user_id=request.user.id, is_delete=True)
            user_instance.save()
            msg = _(f"Clone of '{instance.name}'")
            addlogmsg(request.user.username, new_instance.name, msg)

            if app_settings.CLONE_INSTANCE_AUTO_MIGRATE == 'True':
                new_compute = Compute.objects.order_by('?').first()
                utils.migrate_instance(new_compute, new_instance, request.user, xml_del=True, offline=True)

            return redirect(reverse('instances:instance', args=[new_instance.id]))
        except Exception as e:
            messages.error(request, e)

    return redirect(request.META.get('HTTP_REFERER') + '#clone')


def update_console(request, pk):
    instance = get_instance(request.user, pk)
    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except:
        userinstance = UserInstance(is_vnc=False)

    if request.user.is_superuser or request.user.is_staff or userinstance.is_vnc:
        form = ConsoleForm(request.POST or None)
        if form.is_valid():
            if 'generate_password' in form.changed_data or 'clear_password' in form.changed_data or 'password' in form.changed_data:
                if form.cleaned_data['generate_password']:
                    password = randomPasswd()
                elif form.cleaned_data['clear_password']:
                    password = ''
                else:
                    password = form.cleaned_data['password']

                if not instance.proxy.set_console_passwd(password):
                    msg = _("Error setting console password. " + "You should check that your instance have an graphic device.")
                    messages.error(request, msg)
                else:
                    msg = _("Set VNC password")
                    addlogmsg(request.user.username, instance.name, msg)

            if 'keymap' in form.changed_data or 'clear_keymap' in form.changed_data:
                if form.cleaned_data['clear_keymap']:
                    instance.proxy.set_console_keymap('')
                else:
                    instance.proxy.set_console_keymap(form.cleaned_data['keymap'])
                msg = _("Set VNC keymap")
                addlogmsg(request.user.username, instance.name, msg)

            if 'type' in form.changed_data:
                instance.proxy.set_console_type(form.cleaned_data['type'])
                msg = _("Set VNC type")
                addlogmsg(request.user.username, instance.name, msg)

            if 'listen_on' in form.changed_data:
                instance.proxy.set_console_listen_addr(form.cleaned_data['listen_on'])
                msg = _("Set VNC listen address")
                addlogmsg(request.user.username, instance.name, msg)

    return redirect(request.META.get('HTTP_REFERER') + '#vncsettings')


def change_options(request, pk):
    instance = get_instance(request.user, pk)
    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except:
        userinstance = UserInstance(is_change=False)

    if request.user.is_superuser or request.user.is_staff or userinstance.is_change:
        instance.is_template = request.POST.get('is_template', False)
        instance.save()

        options = {}
        for post in request.POST:
            if post in ['title', 'description']:
                options[post] = request.POST.get(post, '')
        instance.proxy.set_options(options)

        msg = _("Edit options")
        addlogmsg(request.user.username, instance.name, msg)
    return redirect(request.META.get('HTTP_REFERER') + '#options')


def getvvfile(request, pk):
    instance = get_instance(request.user, pk)
    conn = wvmInstances(
        instance.compute.hostname,
        instance.compute.login,
        instance.compute.password,
        instance.compute.type,
    )

    msg = _("Send console.vv file")
    addlogmsg(request.user.username, instance.name, msg)
    response = HttpResponse(content='', content_type='application/x-virt-viewer', status=200, reason=None, charset='utf-8')
    response.writelines('[virt-viewer]\n')
    response.writelines('type=' + conn.graphics_type(instance.name) + '\n')
    response.writelines('host=' + conn.graphics_listen(instance.name) + '\n')
    response.writelines('port=' + conn.graphics_port(instance.name) + '\n')
    response.writelines('title=' + conn.domain_name(instance.name) + '\n')
    response.writelines('password=' + conn.graphics_passwd(instance.name) + '\n')
    response.writelines('enable-usbredir=1\n')
    response.writelines('disable-effects=all\n')
    response.writelines('secure-attention=ctrl+alt+ins\n')
    response.writelines('release-cursor=ctrl+alt\n')
    response.writelines('fullscreen=1\n')
    response.writelines('delete-this-file=1\n')
    response['Content-Disposition'] = 'attachment; filename="console.vv"'
    return response


@superuser_only
def create_instance_select_type(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    conn = None
    storages = list()
    networks = list()
    hypervisors = list()
    meta_prealloc = False
    compute = get_object_or_404(Compute, pk=compute_id)

    conn = wvmCreate(compute.hostname, compute.login, compute.password, compute.type)
    instances = conn.get_instances()
    all_hypervisors = conn.get_hypervisors_machines()

    # Supported hypervisors by webvirtcloud: i686, x86_64(for now)
    supported_arch = ["x86_64", "i686", "aarch64", "armv7l", "ppc64", "ppc64le", "s390x"]
    hypervisors = [hpv for hpv in all_hypervisors.keys() if hpv in supported_arch]
    default_machine = app_settings.INSTANCE_MACHINE_DEFAULT_TYPE
    default_arch = app_settings.INSTANCE_ARCH_DEFAULT_TYPE

    if request.method == 'POST':
        if 'create_xml' in request.POST:
            xml = request.POST.get('dom_xml', '')
            try:
                name = util.get_xml_path(xml, '/domain/name')
            except util.etree.Error as err:
                name = None
            if name in instances:
                error_msg = _("A virtual machine with this name already exists")
                messages.error(request, error_msg)
            else:
                conn._defineXML(xml)
                utils.refr(compute)
                instance = compute.instance_set.get(name=name)
                return redirect(reverse('instances:instance', args=[instance.id]))

    return render(request, 'create_instance_w1.html', locals())


@superuser_only
def create_instance(request, compute_id, arch, machine):
    """
    :param request:
    :param compute_id:
    :param arch:
    :param machine:
    :return:
    """

    conn = None
    storages = list()
    networks = list()
    hypervisors = list()
    firmwares = list()
    meta_prealloc = False
    compute = get_object_or_404(Compute, pk=compute_id)
    flavors = Flavor.objects.filter().order_by('id')
    appsettings = AppSettings.objects.all()

    try:
        conn = wvmCreate(compute.hostname, compute.login, compute.password, compute.type)

        default_firmware = app_settings.INSTANCE_FIRMWARE_DEFAULT_TYPE
        default_cpu_mode = app_settings.INSTANCE_CPU_DEFAULT_MODE
        instances = conn.get_instances()
        videos = conn.get_video_models(arch, machine)
        cache_modes = sorted(conn.get_cache_modes().items())
        default_cache = app_settings.INSTANCE_VOLUME_DEFAULT_CACHE
        default_io = app_settings.INSTANCE_VOLUME_DEFAULT_IO
        default_zeroes = app_settings.INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES
        default_discard = app_settings.INSTANCE_VOLUME_DEFAULT_DISCARD
        default_disk_format = app_settings.INSTANCE_VOLUME_DEFAULT_FORMAT
        default_disk_owner_uid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
        default_disk_owner_gid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)
        default_scsi_disk_model = app_settings.INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER
        listener_addr = settings.QEMU_CONSOLE_LISTEN_ADDRESSES
        mac_auto = util.randomMAC()
        disk_devices = conn.get_disk_device_types(arch, machine)
        disk_buses = conn.get_disk_bus_types(arch, machine)
        default_bus = app_settings.INSTANCE_VOLUME_DEFAULT_BUS
        networks = sorted(conn.get_networks())
        nwfilters = conn.get_nwfilters()
        storages = sorted(conn.get_storages(only_actives=True))
        default_graphics = app_settings.QEMU_CONSOLE_DEFAULT_TYPE

        dom_caps = conn.get_dom_capabilities(arch, machine)
        caps = conn.get_capabilities(arch)

        virtio_support = conn.is_supports_virtio(arch, machine)
        hv_supports_uefi = conn.supports_uefi_xml(dom_caps["loader_enums"])
        # Add BIOS
        label = conn.label_for_firmware_path(arch, None)
        if label: firmwares.append(label)
        # Add UEFI
        loader_path = conn.find_uefi_path_for_arch(arch, dom_caps["loaders"])
        label = conn.label_for_firmware_path(arch, loader_path)
        if label: firmwares.append(label)
        firmwares = list(set(firmwares))

        flavor_form = FlavorForm()

        if conn:
            if not storages:
                raise libvirtError(_("You haven't defined any storage pools"))
            if not networks:
                raise libvirtError(_("You haven't defined any network pools"))

            if request.method == 'POST':
                if 'create' in request.POST:
                    firmware = dict()
                    volume_list = list()
                    is_disk_created = False
                    clone_path = ""
                    form = NewVMForm(request.POST)
                    if form.is_valid():
                        data = form.cleaned_data
                        if data['meta_prealloc']:
                            meta_prealloc = True
                        if instances:
                            if data['name'] in instances:
                                raise libvirtError(_("A virtual machine with this name already exists"))
                            if Instance.objects.filter(name__exact=data['name']):
                                raise libvirtError(_("There is an instance with same name. Remove it and try again!"))

                        if data['hdd_size']:
                            if not data['mac']:
                                raise libvirtError(_("No Virtual Machine MAC has been entered"))
                            else:
                                path = conn.create_volume(data['storage'], data['name'], data['hdd_size'], default_disk_format,
                                                        meta_prealloc, default_disk_owner_uid, default_disk_owner_gid)
                                volume = dict()
                                volume['device'] = 'disk'
                                volume['path'] = path
                                volume['type'] = conn.get_volume_type(path)
                                volume['cache_mode'] = data['cache_mode']
                                volume['bus'] = default_bus
                                if volume['bus'] == 'scsi':
                                    volume['scsi_model'] = default_scsi_disk_model
                                volume['discard_mode'] = default_discard
                                volume['detect_zeroes_mode'] = default_zeroes
                                volume['io_mode'] = default_io

                                volume_list.append(volume)
                                is_disk_created = True

                        elif data['template']:
                            templ_path = conn.get_volume_path(data['template'])
                            dest_vol = conn.get_volume_path(data["name"] + ".img", data['storage'])
                            if dest_vol:
                                raise libvirtError(_("Image has already exist. Please check volumes or change instance name"))
                            else:
                                clone_path = conn.clone_from_template(data['name'], templ_path, data['storage'], meta_prealloc,
                                                                    default_disk_owner_uid, default_disk_owner_gid)
                                volume = dict()
                                volume['path'] = clone_path
                                volume['type'] = conn.get_volume_type(clone_path)
                                volume['device'] = 'disk'
                                volume['cache_mode'] = data['cache_mode']
                                volume['bus'] = default_bus
                                if volume['bus'] == 'scsi':
                                    volume['scsi_model'] = default_scsi_disk_model
                                volume['discard_mode'] = default_discard
                                volume['detect_zeroes_mode'] = default_zeroes
                                volume['io_mode'] = default_io

                                volume_list.append(volume)
                                is_disk_created = True
                        else:
                            if not data['images']:
                                raise libvirtError(_("First you need to create or select an image"))
                            else:
                                for idx, vol in enumerate(data['images'].split(',')):
                                    path = conn.get_volume_path(vol)
                                    volume = dict()
                                    volume['path'] = path
                                    volume['type'] = conn.get_volume_type(path)
                                    volume['device'] = request.POST.get('device' + str(idx), '')
                                    volume['bus'] = request.POST.get('bus' + str(idx), '')
                                    if volume['bus'] == 'scsi':
                                        volume['scsi_model'] = default_scsi_disk_model
                                    volume['cache_mode'] = data['cache_mode']
                                    volume['discard_mode'] = default_discard
                                    volume['detect_zeroes_mode'] = default_zeroes
                                    volume['io_mode'] = default_io

                                    volume_list.append(volume)
                        if data['cache_mode'] not in conn.get_cache_modes():
                            error_msg = _("Invalid cache mode")
                            raise libvirtError

                        if 'UEFI' in data["firmware"]:
                            firmware["loader"] = data["firmware"].split(":")[1].strip()
                            firmware["secure"] = 'no'
                            firmware["readonly"] = 'yes'
                            firmware["type"] = 'pflash'
                            if 'secboot' in firmware["loader"] and machine != 'q35':
                                messages.warning(
                                    request, "Changing machine type from '%s' to 'q35' "
                                    "which is required for UEFI secure boot." % machine)
                                machine = 'q35'
                                firmware["secure"] = 'yes'

                        uuid = util.randomUUID()
                        try:
                            conn.create_instance(name=data['name'],
                                                memory=data['memory'],
                                                vcpu=data['vcpu'],
                                                vcpu_mode=data['vcpu_mode'],
                                                uuid=uuid,
                                                arch=arch,
                                                machine=machine,
                                                firmware=firmware,
                                                volumes=volume_list,
                                                networks=data['networks'],
                                                virtio=data['virtio'],
                                                listen_addr=data["listener_addr"],
                                                nwfilter=data["nwfilter"],
                                                graphics=data["graphics"],
                                                video=data["video"],
                                                console_pass=data["console_pass"],
                                                mac=data['mac'],
                                                qemu_ga=data['qemu_ga'])
                            create_instance = Instance(compute_id=compute_id, name=data['name'], uuid=uuid)
                            create_instance.save()
                            msg = _("Instance is created")
                            messages.success(request, msg)
                            addlogmsg(request.user.username, create_instance.name, msg)
                            return redirect(reverse('instances:instance', args=[create_instance.id]))
                        except libvirtError as lib_err:
                            if data['hdd_size'] or len(volume_list) > 0:
                                if is_disk_created:
                                    for vol in volume_list:
                                        conn.delete_volume(vol['path'])
                            messages.error(request, lib_err)
            conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)
    return render(request, 'create_instance_w2.html', locals())


@superuser_only
def flavor_create(request):
    form = FlavorForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, _('Flavor Created'))
        return redirect(request.META.get('HTTP_REFERER'))

    return render(
        request,
        'common/form.html',
        {
            'form': form,
            'title': _('Create Flavor')
        },
    )


@superuser_only
def flavor_update(request, pk):
    flavor = get_object_or_404(Flavor, pk=pk)
    form = FlavorForm(request.POST or None, instance=flavor)
    if form.is_valid():
        form.save()
        messages.success(request, _('Flavor Updated'))
        return redirect(request.META.get('HTTP_REFERER'))

    return render(
        request,
        'common/form.html',
        {
            'form': form,
            'title': _('Update Flavor')
        },
    )


@superuser_only
def flavor_delete(request, pk):
    flavor = get_object_or_404(Flavor, pk=pk)
    if request.method == 'POST':
        flavor.delete()
        messages.success(request, _('Flavor Deleted'))
        return redirect(request.META.get('HTTP_REFERER'))

    return render(
        request,
        'common/confirm_delete.html',
        {'object': flavor},
    )
