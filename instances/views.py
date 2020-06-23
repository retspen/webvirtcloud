import os
import time
import json
import socket
import crypt
import re
import string
import random
from bisect import insort
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.shortcuts import render, get_object_or_404
from django.utils.translation import ugettext_lazy as _
from computes.models import Compute
from instances.models import Instance
from appsettings.models import AppSettings
from django.contrib.auth.models import User
from accounts.models import UserInstance, UserSSHKey
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.connection import connection_manager
from vrtManager.create import wvmCreate
from vrtManager.storage import wvmStorage
from vrtManager.util import randomPasswd
from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE, VIR_DOMAIN_UNDEFINE_KEEP_NVRAM, VIR_DOMAIN_UNDEFINE_NVRAM
from logs.views import addlogmsg
from django.conf import settings
from django.contrib import messages
from collections import OrderedDict


def index(request):
    """
    :param request:
    :return:
    """
    return HttpResponseRedirect(reverse('instances:index'))


def allinstances(request):
    """
    INSTANCES LIST FOR ALL HOSTS
    :param request:
    :return:
    """
    all_host_vms = OrderedDict()
    error_messages = []
    computes = Compute.objects.all().order_by("name")
    computes_data = get_hosts_status(computes)

    if not request.user.is_superuser:
        all_user_vms = get_user_instances(request)
    else:
        for comp in computes:
            try:
                all_host_vms.update(get_host_instances(request, comp))
            except libvirtError as lib_err:
                error_messages.append(lib_err)

    if request.method == 'POST':
        try:
            return instances_actions(request)
        except libvirtError as lib_err:
            error_messages.append(lib_err)
            addlogmsg(request.user.username, request.POST.get("name", "instance"), lib_err)

    view_style = AppSettings.objects.get(key="VIEW_INSTANCES_LIST_STYLE").value

    return render(request, 'allinstances.html', locals())


def instances(request, compute_id):
    """
    :param request:
    :param compute_id
    :return:
    """
    all_host_vms = OrderedDict()
    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)

    if not request.user.is_superuser:
        all_user_vms = get_user_instances(request)
    else:
        try:
            all_host_vms = get_host_instances(request, compute)
        except libvirtError as lib_err:
            error_messages.append(lib_err)

    if request.method == 'POST':
        try:
            return instances_actions(request)
        except libvirtError as lib_err:
            error_messages.append(lib_err)
            addlogmsg(request.user.username, request.POST.get("name", "instance"), lib_err)

    return render(request, 'instances.html', locals())


def instance(request, compute_id, vname):
    """
    :param request:
    :param compute_id:
    :param vname:
    :return:
    """

    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)
    computes = Compute.objects.all().order_by('name')
    computes_count = computes.count()
    users = User.objects.all().order_by('username')
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)
    appsettings = AppSettings.objects.all()
    keymaps = settings.QEMU_KEYMAPS
    console_types = appsettings.get(key="QEMU_CONSOLE_DEFAULT_TYPE").choices_as_list
    console_listen_addresses = settings.QEMU_CONSOLE_LISTEN_ADDRESSES
    bottom_bar = appsettings.get(key="VIEW_INSTANCE_DETAIL_BOTTOM_BAR").value
    try:
        userinstance = UserInstance.objects.get(instance__compute_id=compute_id,
                                                instance__name=vname,
                                                user__id=request.user.id)
    except UserInstance.DoesNotExist:
        userinstance = None

    if not request.user.is_superuser:
        if not userinstance:
            return HttpResponseRedirect(reverse('index'))

    def filesizefstr(size_str):
        if size_str == '':
            return 0
        size_str = size_str.upper().replace("B", "")
        if size_str[-1] == 'K':
            return int(float(size_str[:-1])) << 10
        elif size_str[-1] == 'M':
            return int(float(size_str[:-1])) << 20
        elif size_str[-1] == 'G':
            return int(float(size_str[:-1])) << 30
        elif size_str[-1] == 'T':
            return int(float(size_str[:-1])) << 40
        elif size_str[-1] == 'P':
            return int(float(size_str[:-1])) << 50
        else:
            return int(float(size_str))

    def get_clone_free_names(size=10):
        prefix = appsettings.get(key="CLONE_INSTANCE_DEFAULT_PREFIX").value
        free_names = []
        existing_names = [i.name for i in Instance.objects.filter(name__startswith=prefix)]
        index = 1
        while len(free_names) < size:
            new_name = prefix + str(index)
            if new_name not in existing_names:
                free_names.append(new_name)
            index += 1
        return free_names

    def check_user_quota(instance, cpu, memory, disk_size):
        ua = request.user
        msg = ""

        if request.user.is_superuser:
            return msg

        user_instances = UserInstance.objects.filter(user_id=request.user.id, instance__is_template=False)
        instance += user_instances.count()
        for usr_inst in user_instances:
            if connection_manager.host_is_up(usr_inst.instance.compute.type,
                                             usr_inst.instance.compute.hostname):
                conn = wvmInstance(usr_inst.instance.compute.hostname,
                                   usr_inst.instance.compute.login,
                                   usr_inst.instance.compute.password,
                                   usr_inst.instance.compute.type,
                                   usr_inst.instance.name)
                cpu += int(conn.get_vcpu())
                memory += int(conn.get_memory())
                for disk in conn.get_disk_devices():
                    if disk['size']:
                        disk_size += int(disk['size']) >> 30

        if ua.max_instances > 0 and instance > ua.max_instances:
            quota_debug = appsettings.get(key="QUOTA_DEBUG").value
            msg = "instance"
            if quota_debug:
                msg += f" ({instance} > {ua.max_instances})"
        if ua.max_cpus > 0 and cpu > ua.max_cpus:
            msg = "cpu"
            if quota_debug:
                msg += f" ({cpu} > {ua.max_cpus})"
        if ua.max_memory > 0 and memory > ua.max_memory:
            msg = "memory"
            if quota_debug:
                msg += f" ({memory} > {ua.max_memory})"
        if ua.max_disk_size > 0 and disk_size > ua.max_disk_size:
            msg = "disk"
            if quota_debug:
                msg += f" ({disk_size} > {ua.max_disk_size})"
        return msg

    def get_new_disk_dev(media, disks, bus):
        existing_disk_devs = []
        existing_media_devs = []
        if bus == "virtio":
            dev_base = "vd"
        elif bus == "ide":
            dev_base = "hd"
        elif bus == "fdc":
            dev_base = "fd"
        else:
            dev_base = "sd"

        if disks:
            existing_disk_devs = [disk['dev'] for disk in disks]

        # cd-rom bus could be virtio/sata, because of that we should check it also
        if media:
            existing_media_devs = [m['dev'] for m in media]

        for al in string.ascii_lowercase:
            dev = dev_base + al
            if dev not in existing_disk_devs and dev not in existing_media_devs:
                return dev
        raise Exception(_('None available device name'))

    def get_network_tuple(network_source_str):
        network_source_pack = network_source_str.split(":", 1)
        if len(network_source_pack) > 1:
            return network_source_pack[1], network_source_pack[0]
        else:
            return network_source_pack[0], 'net'

    def migrate_instance(new_compute, instance, live=False, unsafe=False, xml_del=False, offline=False, autoconverge=False, compress=False, postcopy=False):
        status = connection_manager.host_is_up(new_compute.type, new_compute.hostname)
        if not status:
            return
        if new_compute == instance.compute:
            return
        try:
            conn_migrate = wvmInstances(new_compute.hostname,
                                        new_compute.login,
                                        new_compute.password,
                                        new_compute.type)

            conn_migrate.moveto(conn, instance.name, live, unsafe, xml_del, offline, autoconverge, compress, postcopy)
        finally:
            conn_migrate.close()

        instance.compute = new_compute
        instance.save()

        conn_new = wvmInstance(new_compute.hostname,
                               new_compute.login,
                               new_compute.password,
                               new_compute.type,
                               instance.name)
        if autostart:
            conn_new.set_autostart(1)
            conn_new.close()
        msg = _(f"Migrate to {new_compute.hostname}")
        addlogmsg(request.user.username, instance.name, msg)

    try:
        conn = wvmInstance(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type,
                           vname)

        status = conn.get_status()
        autostart = conn.get_autostart()
        bootmenu = conn.get_bootmenu()
        boot_order = conn.get_bootorder()
        arch = conn.get_arch()
        machine = conn.get_machine_type()
        firmware = conn.get_loader()
        nvram = conn.get_nvram()
        vcpu = conn.get_vcpu()
        cur_vcpu = conn.get_cur_vcpu()
        vcpus = conn.get_vcpus()
        uuid = conn.get_uuid()
        memory = conn.get_memory()
        cur_memory = conn.get_cur_memory()
        title = conn.get_title()
        description = conn.get_description()
        networks = conn.get_net_devices()
        qos = conn.get_all_qos()
        disks = conn.get_disk_devices()
        media = conn.get_media_devices()
        if len(media) != 0:
            media_iso = sorted(conn.get_iso_media())
        else:
            media_iso = []

        vcpu_range = conn.get_max_cpus()
        memory_range = [256, 512, 768, 1024, 2048, 3072, 4096, 6144, 8192, 16384]
        if memory not in memory_range:
            insort(memory_range, memory)
        if cur_memory not in memory_range:
            insort(memory_range, cur_memory)
        telnet_port = conn.get_telnet_port()
        console_type = conn.get_console_type()
        console_port = conn.get_console_port()
        console_keymap = conn.get_console_keymap()
        console_listen_address = conn.get_console_listen_addr()
        guest_agent = False if conn.get_guest_agent() is None else True
        guest_agent_ready = conn.is_agent_ready()
        video_model = conn.get_video_model()
        snapshots = sorted(conn.get_snapshot(), reverse=True, key=lambda k: k['date'])
        inst_xml = conn._XMLDesc(VIR_DOMAIN_XML_SECURE)
        has_managed_save_image = conn.get_managed_save_image()
        console_passwd = conn.get_console_passwd()
        clone_free_names = get_clone_free_names()
        user_quota_msg = check_user_quota(0, 0, 0, 0)
        cache_modes = sorted(conn.get_cache_modes().items())
        io_modes = sorted(conn.get_io_modes().items())
        discard_modes = sorted(conn.get_discard_modes().items())
        detect_zeroes_modes = sorted(conn.get_detect_zeroes_modes().items())
        default_bus = appsettings.get(key="INSTANCE_VOLUME_DEFAULT_BUS").value
        default_io = appsettings.get(key="INSTANCE_VOLUME_DEFAULT_IO").value
        default_discard = appsettings.get(key="INSTANCE_VOLUME_DEFAULT_DISCARD").value
        default_zeroes = appsettings.get(key="INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES").value
        default_cache = appsettings.get(key="INSTANCE_VOLUME_DEFAULT_CACHE").value
        default_format = appsettings.get(key="INSTANCE_VOLUME_DEFAULT_FORMAT").value
        default_disk_owner_uid = int(appsettings.get(key="INSTANCE_VOLUME_DEFAULT_OWNER_UID").value)
        default_disk_owner_gid = int(appsettings.get(key="INSTANCE_VOLUME_DEFAULT_OWNER_GID").value)
        
        formats = conn.get_image_formats()

        show_access_root_password = appsettings.get(key="SHOW_ACCESS_ROOT_PASSWORD").value
        show_access_ssh_keys = appsettings.get(key="SHOW_ACCESS_SSH_KEYS").value
        clone_instance_auto_name = appsettings.get(key="CLONE_INSTANCE_AUTO_NAME").value
        

        try:
            instance = Instance.objects.get(compute_id=compute_id, name=vname)
            if instance.uuid != uuid:
                instance.uuid = uuid
                instance.save()
                msg = _(f"Fixing UUID {uuid}")
                addlogmsg(request.user.username, instance.name, msg)
        except Instance.DoesNotExist:
            instance = Instance(compute_id=compute_id, name=vname, uuid=uuid)
            instance.save()
            msg = _("Instance does not exist: Creating new instance")
            addlogmsg(request.user.username, instance.name, msg)

        userinstances = UserInstance.objects.filter(instance=instance).order_by('user__username')
        allow_admin_or_not_template = request.user.is_superuser or request.user.is_staff or not instance.is_template

        # Host resources
        vcpu_host = len(vcpu_range)
        memory_host = conn.get_max_memory()
        bus_host = conn.get_disk_bus_types(arch, machine)
        videos_host = conn.get_video_models(arch, machine)
        networks_host = sorted(conn.get_networks())
        nwfilters_host = conn.get_nwfilters()
        storages_host = sorted(conn.get_storages(True))
        net_models_host = conn.get_network_models()

        try:
            interfaces_host = sorted(conn.get_ifaces())
        except Exception as e:
            addlogmsg(request.user.username, instance.name, e)
            error_messages.append(e)

        if request.method == 'POST':
            if 'poweron' in request.POST:
                if instance.is_template:
                    msg = _("Templates cannot be started.")
                    error_messages.append(msg)
                else:
                    conn.start()
                    msg = _("Power On")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#poweron')

            if 'powercycle' in request.POST:
                conn.force_shutdown()
                conn.start()
                msg = _("Power Cycle")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#powercycle')

            if 'poweroff' in request.POST:
                conn.shutdown()
                msg = _("Power Off")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#poweroff')

            if 'powerforce' in request.POST:
                conn.force_shutdown()
                msg = _("Force Off")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#powerforce')

            if 'delete' in request.POST and (request.user.is_superuser or userinstance.is_delete):
                if conn.get_status() == 1:
                    conn.force_shutdown()
                if request.POST.get('delete_disk', ''):
                    for snap in snapshots:
                        conn.snapshot_delete(snap['name'])
                    conn.delete_all_disks()

                if request.POST.get('delete_nvram', ''):
                    conn.delete(VIR_DOMAIN_UNDEFINE_NVRAM)
                else:
                    conn.delete(VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)

                instance = Instance.objects.get(compute_id=compute_id, name=vname)
                instance_name = instance.name
                instance.delete()

                try:
                    del_userinstance = UserInstance.objects.filter(instance__compute_id=compute_id,
                                                                   instance__name=vname)
                    del_userinstance.delete()
                except UserInstance.DoesNotExist:
                    pass

                msg = _("Destroy")
                addlogmsg(request.user.username, instance_name, msg)

                return HttpResponseRedirect(reverse('instances:index'))

            if 'rootpasswd' in request.POST:
                passwd = request.POST.get('passwd', '')
                passwd_hash = crypt.crypt(passwd, '$6$kgPoiREy')
                data = {'action': 'password', 'passwd': passwd_hash, 'vname': vname}

                if conn.get_status() == 5:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.connect((compute.hostname, 16510))
                    s.send(json.dumps(data))
                    result = json.loads(s.recv(1024))
                    s.close()
                    msg = _("Reset root password")
                    addlogmsg(request.user.username, instance.name, msg)

                    if result['return'] == 'success':
                        messages.success(request, msg)
                    else:
                        error_messages.append(msg)
                else:
                    msg = _("Please shutdown down your instance and then try again")
                    error_messages.append(msg)

            if 'addpublickey' in request.POST:
                sshkeyid = request.POST.get('sshkeyid', '')
                publickey = UserSSHKey.objects.get(id=sshkeyid)
                data = {'action': 'publickey', 'key': publickey.keypublic, 'vname': vname}

                if conn.get_status() == 5:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.connect((compute.hostname, 16510))
                    s.send(json.dumps(data))
                    result = json.loads(s.recv(1024))
                    s.close()
                    msg = _(f"Installed new SSH public key {publickey.keyname}")
                    addlogmsg(request.user.username, instance.name, msg)

                    if result['return'] == 'success':
                        messages.success(request, msg)
                    else:
                        error_messages.append(msg)
                else:
                    msg = _("Please shutdown down your instance and then try again")
                    error_messages.append(msg)

            if 'resizevm_cpu' in request.POST and (
                    request.user.is_superuser or request.user.is_staff or userinstance.is_change):
                new_vcpu = request.POST.get('vcpu', '')
                new_cur_vcpu = request.POST.get('cur_vcpu', '')

                quota_msg = check_user_quota(0, int(new_vcpu) - vcpu, 0, 0)
                if not request.user.is_superuser and quota_msg:
                    msg = _(f"User {quota_msg} quota reached, cannot resize CPU of '{instance.name}'!")
                    error_messages.append(msg)
                else:
                    cur_vcpu = new_cur_vcpu
                    vcpu = new_vcpu
                    conn.resize_cpu(cur_vcpu, vcpu)
                    msg = _("Resize CPU")
                    addlogmsg(request.user.username, instance.name, msg)
                    messages.success(request, msg)
                return HttpResponseRedirect(request.get_full_path() + '#resize')

            if 'resizevm_mem' in request.POST and (request.user.is_superuser or
                                                   request.user.is_staff or
                                                   userinstance.is_change):
                new_memory = request.POST.get('memory', '')
                new_memory_custom = request.POST.get('memory_custom', '')
                if new_memory_custom:
                    new_memory = new_memory_custom
                new_cur_memory = request.POST.get('cur_memory', '')
                new_cur_memory_custom = request.POST.get('cur_memory_custom', '')
                if new_cur_memory_custom:
                    new_cur_memory = new_cur_memory_custom
                quota_msg = check_user_quota(0, 0, int(new_memory) - memory, 0)
                if not request.user.is_superuser and quota_msg:
                    msg = _(f"User {quota_msg} quota reached, cannot resize memory of '{instance.name}'!")
                    error_messages.append(msg)
                else:
                    cur_memory = new_cur_memory
                    memory = new_memory
                    conn.resize_mem(cur_memory, memory)
                    msg = _("Resize Memory")
                    addlogmsg(request.user.username, instance.name, msg)
                    messages.success(request, msg)
                return HttpResponseRedirect(request.get_full_path() + '#resize')

            if 'resizevm_disk' in request.POST and (
                    request.user.is_superuser or request.user.is_staff or userinstance.is_change):
                disks_new = list()
                for disk in disks:
                    input_disk_size = filesizefstr(request.POST.get('disk_size_' + disk['dev'], ''))
                    if input_disk_size > disk['size'] + (64 << 20):
                        disk['size_new'] = input_disk_size
                        disks_new.append(disk)
                disk_sum = sum([disk['size'] >> 30 for disk in disks_new])
                disk_new_sum = sum([disk['size_new'] >> 30 for disk in disks_new])
                quota_msg = check_user_quota(0, 0, 0, disk_new_sum - disk_sum)
                if not request.user.is_superuser and quota_msg:
                    msg = _(f"User {quota_msg} quota reached, cannot resize disks of '{instance.name}'!")
                    error_messages.append(msg)
                else:
                    conn.resize_disk(disks_new)
                    msg = _("Disk resize")
                    addlogmsg(request.user.username, instance.name, msg)
                    messages.success(request, msg)
                return HttpResponseRedirect(request.get_full_path() + '#resize')

            if 'add_new_vol' in request.POST and allow_admin_or_not_template:
                conn_create = wvmCreate(compute.hostname,
                                        compute.login,
                                        compute.password,
                                        compute.type)
                storage = request.POST.get('storage', '')
                name = request.POST.get('name', '')
                format = request.POST.get('format', default_format)
                size = request.POST.get('size', 0)
                meta_prealloc = True if request.POST.get('meta_prealloc', False) else False
                bus = request.POST.get('bus', default_bus)
                cache = request.POST.get('cache', default_cache)
                target_dev = get_new_disk_dev(media, disks, bus)

                source = conn_create.create_volume(storage, name, size, format, meta_prealloc, default_disk_owner_uid, default_disk_owner_gid)
                conn.attach_disk(target_dev, source, target_bus=bus, driver_type=format, cache_mode=cache)
                msg = _(f"Attach new disk {name} ({format})")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'add_existing_vol' in request.POST and allow_admin_or_not_template:
                storage = request.POST.get('selected_storage', '')
                name = request.POST.get('vols', '')
                bus = request.POST.get('bus', default_bus)
                cache = request.POST.get('cache', default_cache)

                conn_create = wvmStorage(compute.hostname,
                                         compute.login,
                                         compute.password,
                                         compute.type,
                                         storage)

                driver_type = conn_create.get_volume_type(name)
                path = conn_create.get_target_path()
                target_dev = get_new_disk_dev(media, disks, bus)
                source = f"{path}/{name}"

                conn.attach_disk(target_dev, source, target_bus=bus, driver_type=driver_type, cache_mode=cache)
                msg = _(f"Attach Existing disk: {target_dev}")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

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
                cache = request.POST.get('vol_cache', default_cache)
                io = request.POST.get('vol_io_mode', default_io)
                discard = request.POST.get('vol_discard_mode', default_discard)
                zeroes = request.POST.get('vol_detect_zeroes', default_zeroes)
                new_target_dev = get_new_disk_dev(media, disks, new_bus)

                if new_bus != bus:
                    conn.detach_disk(target_dev)
                    conn.attach_disk(new_target_dev, new_path, target_bus=new_bus,
                                    driver_type=format, cache_mode=cache,
                                    readonly=readonly, shareable=shareable, serial=serial,
                                    io_mode=io, discard_mode=discard, detect_zeroes_mode=zeroes)
                else:
                    conn.edit_disk(target_dev, new_path, readonly, shareable, new_bus, serial, format,
                                   cache, io, discard, zeroes)

                if not conn.get_status() == 5:
                    messages.success(request, _("Volume changes are applied. " +
                                                "But it will be activated after shutdown"))
                else:
                    messages.success(request, _("Volume is changed successfully."))
                msg = _(f"Edit disk: {target_dev}")
                addlogmsg(request.user.username, instance.name, msg)

                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'delete_vol' in request.POST and allow_admin_or_not_template:
                storage = request.POST.get('storage', '')
                conn_delete = wvmStorage(compute.hostname,
                                         compute.login,
                                         compute.password,
                                         compute.type,
                                         storage)
                dev = request.POST.get('dev', '')
                path = request.POST.get('path', '')
                name = request.POST.get('name', '')

                msg = _(f"Delete disk: {dev}")
                conn.detach_disk(dev)
                try:
                    conn_delete.del_volume(name)
                except libvirtError as err:
                    msg = _(f"The disk: {dev} is detached but not deleted. Error: {err}")
                    messages.warning(request, msg)

                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'detach_vol' in request.POST and allow_admin_or_not_template:
                dev = request.POST.get('detach_vol', '')
                path = request.POST.get('path', '')
                conn.detach_disk(dev)
                msg = _(f"Detach disk: {dev}")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'add_cdrom' in request.POST and allow_admin_or_not_template:
                bus = request.POST.get('bus', 'ide' if machine == 'pc' else 'sata')
                target = get_new_disk_dev(media, disks, bus)
                conn.attach_disk(target, "", disk_device='cdrom', cache_mode='none', target_bus=bus, readonly=True)
                msg = _(f"Add CD-ROM: {target}")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'detach_cdrom' in request.POST and allow_admin_or_not_template:
                dev = request.POST.get('detach_cdrom', '')
                conn.detach_disk(dev)
                msg = _(f'Detach CD-ROM: {dev}')
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'umount_iso' in request.POST and allow_admin_or_not_template:
                image = request.POST.get('path', '')
                dev = request.POST.get('umount_iso', '')
                conn.umount_iso(dev, image)
                msg = _(f"Mount media: {dev}")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'mount_iso' in request.POST and allow_admin_or_not_template:
                image = request.POST.get('media', '')
                dev = request.POST.get('mount_iso', '')
                conn.mount_iso(dev, image)
                msg = _(f"Umount media: {dev}")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#disks')

            if 'snapshot' in request.POST and allow_admin_or_not_template:
                name = request.POST.get('name', '')
                conn.create_snapshot(name)
                msg = _(f"New snapshot : {name}")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#managesnapshot')

            if 'delete_snapshot' in request.POST and allow_admin_or_not_template:
                snap_name = request.POST.get('name', '')
                conn.snapshot_delete(snap_name)
                msg = _(f"Delete snapshot : {snap_name}")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#managesnapshot')

            if 'revert_snapshot' in request.POST and allow_admin_or_not_template:
                snap_name = request.POST.get('name', '')
                conn.snapshot_revert(snap_name)
                msg = _("Successful revert snapshot: ")
                msg += snap_name
                messages.success(request, msg)
                msg = _("Revert snapshot")
                addlogmsg(request.user.username, instance.name, msg)

            if request.user.is_superuser:
                if 'suspend' in request.POST:
                    conn.suspend()
                    msg = _("Suspend")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#resume')

                if 'resume' in request.POST:
                    conn.resume()
                    msg = _("Resume")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#suspend')

                if 'set_vcpu' in request.POST:
                    id = request.POST.get('id', '')
                    enabled = request.POST.get('set_vcpu', '')
                    if enabled == 'True':
                        conn.set_vcpu(id, 1)
                    else:
                        conn.set_vcpu(id, 0)
                    msg = _(f"VCPU {id} is enabled={enabled}")
                    messages.success(request, msg)
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#resize')

                if 'set_vcpu_hotplug' in request.POST:
                    status = request.POST.get('vcpu_hotplug', '')
                    msg = _(f"VCPU Hot-plug is enabled={status}")
                    try:
                        conn.set_vcpu_hotplug(eval(status))
                    except libvirtError as lib_err:
                        messages.error(request, lib_err)
                    messages.success(request, msg)
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#resize')

                if 'set_autostart' in request.POST:
                    conn.set_autostart(1)
                    msg = _("Set autostart")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#boot_opt')

                if 'unset_autostart' in request.POST:
                    conn.set_autostart(0)
                    msg = _("Unset autostart")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#boot_opt')

                if 'set_bootmenu' in request.POST:
                    conn.set_bootmenu(1)
                    msg = _("Enable boot menu")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#boot_opt')

                if 'unset_bootmenu' in request.POST:
                    conn.set_bootmenu(0)
                    msg = _("Disable boot menu")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#boot_opt')

                if 'set_bootorder' in request.POST:
                    bootorder = request.POST.get('bootorder', '')
                    if bootorder:
                        order_list = {}
                        for idx, val in enumerate(bootorder.split(',')):
                            dev_type, dev = val.split(':', 1)
                            order_list[idx] = {"type": dev_type, "dev": dev}
                        conn.set_bootorder(order_list)
                        msg = _("Set boot order")

                        if not conn.get_status() == 5:
                            messages.success(request, _("Boot menu changes applied. " +
                                                        "But it will be activated after shutdown"))
                        else:
                            messages.success(request, _("Boot order changed successfully."))
                        addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#boot_opt')

                if 'change_xml' in request.POST:
                    exit_xml = request.POST.get('inst_xml', '')
                    if exit_xml:
                        conn._defineXML(exit_xml)
                        msg = _("Edit XML")
                        addlogmsg(request.user.username, instance.name, msg)
                        return HttpResponseRedirect(request.get_full_path() + '#xmledit')

            if request.user.is_superuser or request.user.is_staff or userinstance.is_vnc:
                if 'set_console_passwd' in request.POST:
                    if request.POST.get('auto_pass', ''):
                        passwd = randomPasswd()
                    else:
                        passwd = request.POST.get('console_passwd', '')
                        clear = request.POST.get('clear_pass', False)
                        if clear:
                            passwd = ''
                        if not passwd and not clear:
                            msg = _("Enter the console password or select Generate")
                            error_messages.append(msg)
                    if not error_messages:
                        if not conn.set_console_passwd(passwd):
                            msg = _("Error setting console password. " +
                                    "You should check that your instance have an graphic device.")
                            error_messages.append(msg)
                        else:
                            msg = _("Set VNC password")
                            addlogmsg(request.user.username, instance.name, msg)
                            return HttpResponseRedirect(request.get_full_path() + '#vncsettings')

                if 'set_console_keymap' in request.POST:
                    keymap = request.POST.get('console_keymap', '')
                    clear = request.POST.get('clear_keymap', False)
                    if clear:
                        conn.set_console_keymap('')
                    else:
                        conn.set_console_keymap(keymap)
                    msg = _("Set VNC keymap")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#vncsettings')

                if 'set_console_type' in request.POST:
                    console_type = request.POST.get('console_type', '')
                    msg = _("Set VNC type")
                    if console_type in console_types:
                        conn.set_console_type(console_type)
                    else:
                        msg = _("Console type not supported")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#vncsettings')

                if 'set_console_listen_address' in request.POST:
                    console_type = request.POST.get('console_listen_address', '')
                    conn.set_console_listen_addr(console_type)
                    msg = _("Set VNC listen address")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#vncsettings')

            if request.user.is_superuser:
                if 'set_guest_agent' in request.POST:
                    status = request.POST.get('guest_agent')
                    if status == 'True':
                        conn.add_guest_agent()
                    if status == 'False':
                        conn.remove_guest_agent()

                    msg = _(f"Set Quest Agent {status}")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#options')

                if 'set_video_model' in request.POST:
                    video_model = request.POST.get('video_model', 'vga')
                    conn.set_video_model(video_model)
                    msg = _("Set Video Model")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#options')

                if 'migrate' in request.POST:

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
                        migrate_instance(new_compute, instance, live, unsafe, xml_del, offline)
                        return HttpResponseRedirect(reverse('instances:instance', args=[new_compute.id, vname]))
                    except libvirtError as err:
                        messages.error(request, err)
                        addlogmsg(request.user.username, instance.name, err)
                        return HttpResponseRedirect(request.get_full_path() + '#migrate')

                if 'change_network' in request.POST:
                    msg = _("Change network")
                    network_data = {}

                    for post in request.POST:
                        if post.startswith('net-source-'):
                            (source, source_type) = get_network_tuple(request.POST.get(post))
                            network_data[post] = source
                            network_data[post + '-type'] = source_type
                        elif post.startswith('net-'):
                            network_data[post] = request.POST.get(post, '')

                    conn.change_network(network_data)
                    addlogmsg(request.user.username, instance.name, msg)
                    msg = _("Network Device Config is changed. Please shutdown instance to activate.")
                    if conn.get_status() != 5: messages.success(request, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#network')

                if 'add_network' in request.POST:
                    msg = _("Add network")
                    mac = request.POST.get('add-net-mac')
                    nwfilter = request.POST.get('add-net-nwfilter')
                    (source, source_type) = get_network_tuple(request.POST.get('add-net-network'))

                    conn.add_network(mac, source, source_type, nwfilter=nwfilter)
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#network')

                if 'delete_network' in request.POST:
                    msg = _("Delete network")
                    mac_address = request.POST.get('delete_network', '')

                    conn.delete_network(mac_address)
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#network')

                if 'set_link_state' in request.POST:
                    mac_address = request.POST.get('mac', '')
                    state = request.POST.get('set_link_state')
                    state = 'down' if state == 'up' else 'up'
                    conn.set_link_state(mac_address, state)
                    msg = _(f"Set Link State: {state}")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#network')

                if 'set_qos' in request.POST:
                    qos_dir = request.POST.get('qos_direction', '')
                    average = request.POST.get('qos_average') or 0
                    peak = request.POST.get('qos_peak') or 0
                    burst = request.POST.get('qos_burst') or 0
                    keys = request.POST.keys()
                    mac_key = [key for key in keys if 'mac' in key]
                    if mac_key: mac = request.POST.get(mac_key[0])

                    try:
                        conn.set_qos(mac, qos_dir, average, peak, burst)
                        if conn.get_status() == 5:
                            messages.success(request, _(f"{qos_dir.capitalize()} QoS is set"))
                        else:
                            messages.success(request,
                                             _(f"{qos_dir.capitalize()} QoS is set. Network XML is changed.") +
                                             _("Stop and start network to activate new config"))

                    except libvirtError as le:
                        messages.error(request, le)
                    return HttpResponseRedirect(request.get_full_path() + '#network')
                if 'unset_qos' in request.POST:
                    qos_dir = request.POST.get('qos_direction', '')
                    mac = request.POST.get('net-mac')
                    conn.unset_qos(mac, qos_dir)

                    if conn.get_status() == 5:
                        messages.success(request, _(f"{qos_dir.capitalize()} QoS is deleted"))
                    else:
                        messages.success(request,
                                         _(f"{qos_dir.capitalize()} QoS is deleted. Network XML is changed. ") +
                                         _("Stop and start network to activate new config."))
                    return HttpResponseRedirect(request.get_full_path() + '#network')

                if 'add_owner' in request.POST:
                    user_id = int(request.POST.get('user_id', ''))

                    if appsettings.get(key="ALLOW_INSTANCE_MULTIPLE_OWNER").value == 'True':
                        check_inst = UserInstance.objects.filter(instance=instance, user_id=user_id)
                    else:
                        check_inst = UserInstance.objects.filter(instance=instance)

                    if check_inst:
                        msg = _("Only one owner is allowed and the one already added")
                        error_messages.append(msg)
                    else:
                        add_user_inst = UserInstance(instance=instance, user_id=user_id)
                        add_user_inst.save()
                        msg = _(f"Added owner {user_id}")
                        addlogmsg(request.user.username, instance.name, msg)
                        return HttpResponseRedirect(request.get_full_path() + '#users')

                if 'del_owner' in request.POST:
                    userinstance_id = int(request.POST.get('userinstance', ''))
                    userinstance = UserInstance.objects.get(pk=userinstance_id)
                    userinstance.delete()
                    msg = _(f"Deleted owner {userinstance_id}")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#users')

            if request.user.is_superuser or request.user.userattributes.can_clone_instances:
                if 'clone' in request.POST:
                    clone_data = dict()
                    clone_data['name'] = request.POST.get('name', '')

                    disk_sum = sum([disk['size'] >> 30 for disk in disks])
                    quota_msg = check_user_quota(1, vcpu, memory, disk_sum)
                    check_instance = Instance.objects.filter(name=clone_data['name'])

                    clone_data['disk_owner_uid'] = default_disk_owner_uid
                    clone_data['disk_owner_gid'] = default_disk_owner_gid

                    for post in request.POST:
                        clone_data[post] = request.POST.get(post, '').strip()

                    if clone_instance_auto_name == 'True' and not clone_data['name']:
                        auto_vname = clone_free_names[0]
                        clone_data['name'] = auto_vname
                        clone_data['clone-net-mac-0'] = _get_dhcp_mac_address(auto_vname)
                        for disk in disks:
                            disk_dev = f"disk-{disk['dev']}"
                            disk_name = get_clone_disk_name(disk, vname, auto_vname)
                            clone_data[disk_dev] = disk_name

                    if not request.user.is_superuser and quota_msg:
                        msg = _(f"User '{quota_msg}' quota reached, cannot create '{clone_data['name']}'!")
                        error_messages.append(msg)
                    elif check_instance:
                        msg = _(f"Instance '{clone_data['name']}' already exists!")
                        error_messages.append(msg)
                    elif not re.match(r'^[a-zA-Z0-9-]+$', clone_data['name']):
                        msg = _(f"Instance name '{clone_data['name']}' contains invalid characters!")
                        error_messages.append(msg)
                    elif not re.match(r'^([0-9A-F]{2})(:?[0-9A-F]{2}){5}$', clone_data['clone-net-mac-0'],
                                      re.IGNORECASE):
                        msg = _(f"Instance MAC '{clone_data['clone-net-mac-0']}' invalid format!")
                        error_messages.append(msg)
                    else:
                        new_instance = Instance(compute_id=compute_id, name=clone_data['name'])
                        # new_instance.save()
                        try:
                            new_uuid = conn.clone_instance(clone_data)
                            new_instance.uuid = new_uuid
                            new_instance.save()
                        except Exception as e:
                            # new_instance.delete()
                            raise e

                        user_instance = UserInstance(instance_id=new_instance.id, user_id=request.user.id, is_delete=True)
                        user_instance.save()

                        msg = _(f"Clone of '{instance.name}'")
                        addlogmsg(request.user.username, new_instance.name, msg)
                        
                        if appsettings.get(key="CLONE_INSTANCE_AUTO_MIGRATE").value == 'True':
                            new_compute = Compute.objects.order_by('?').first()
                            migrate_instance(new_compute, new_instance, xml_del=True, offline=True)
                        return HttpResponseRedirect(
                            reverse('instances:instance', args=[new_instance.compute.id, new_instance.name]))

                if 'change_options' in request.POST and (request.user.is_superuser or request.user.is_staff or userinstance.is_change):
                    instance.is_template = request.POST.get('is_template', False)
                    instance.save()

                    options = {}
                    for post in request.POST:
                        if post in ['title', 'description']:
                            options[post] = request.POST.get(post, '')
                    conn.set_options(options)

                    msg = _("Edit options")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#options')
        conn.close()

    except libvirtError as lib_err:
        error_messages.append(lib_err)
        addlogmsg(request.user.username, vname, lib_err)

    return render(request, 'instance.html', locals())


def inst_status(request, compute_id, vname):
    """
    :param request:
    :param compute_id:
    :param vname:
    :return:
    """

    compute = get_object_or_404(Compute, pk=compute_id)
    response = HttpResponse()
    response['Content-Type'] = "text/javascript"

    try:
        conn = wvmInstance(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type,
                           vname)
        data = json.dumps({'status': conn.get_status()})
        conn.close()
    except libvirtError:
        data = json.dumps({'error': 'Error 500'})
    response.write(data)
    return response


def get_host_instances(request, comp):

    def refresh_instance_database(comp, inst_name, info):
        def get_userinstances_info(instance):
            info = {}
            uis = UserInstance.objects.filter(instance=instance)
            info['count'] = uis.count()
            if info['count'] > 0:
                info['first_user'] = uis[0]
            else:
                info['first_user'] = None
            return info

        # Multiple Instance Name Check
        instances = Instance.objects.filter(name=inst_name)
        if instances.count() > 1:
            for i in instances:
                user_instances_count = UserInstance.objects.filter(instance=i).count()
                if user_instances_count == 0:
                    addlogmsg(request.user.username, i.name, _("Deleting due to multiple(Instance Name) records."))
                    i.delete()

        # Multiple UUID Check
        instances = Instance.objects.filter(uuid=info['uuid'])
        if instances.count() > 1:
            for i in instances:
                if i.name != inst_name:
                    addlogmsg(request.user.username, i.name, _("Deleting due to multiple(UUID) records."))
                    i.delete()

        try:
            inst_on_db = Instance.objects.get(compute_id=comp["id"], name=inst_name)
            if inst_on_db.uuid != info['uuid']:
                inst_on_db.save()

            all_host_vms[comp["id"],
                         comp["name"],
                         comp["status"],
                         comp["cpu"],
                         comp["mem_size"],
                         comp["mem_perc"]][inst_name]['is_template'] = inst_on_db.is_template
            all_host_vms[comp["id"],
                         comp["name"],
                         comp["status"],
                         comp["cpu"],
                         comp["mem_size"],
                         comp["mem_perc"]][inst_name]['userinstances'] = get_userinstances_info(inst_on_db)
        except Instance.DoesNotExist:
            inst_on_db = Instance(compute_id=comp["id"], name=inst_name, uuid=info['uuid'])
            inst_on_db.save()

    all_host_vms = OrderedDict()
    status = connection_manager.host_is_up(comp.type, comp.hostname)

    if status is True:
        conn = wvmHostDetails(comp.hostname, comp.login, comp.password, comp.type)
        comp_node_info = conn.get_node_info()
        comp_mem = conn.get_memory_usage()
        comp_instances = conn.get_host_instances(True)

        if comp_instances:
            comp_info = {
                "id": comp.id,
                "name": comp.name,
                "status": status,
                "cpu": comp_node_info[3],
                "mem_size": comp_node_info[2],
                "mem_perc": comp_mem['percent']
            }
            all_host_vms[comp_info["id"], comp_info["name"], comp_info["status"], comp_info["cpu"],
                         comp_info["mem_size"], comp_info["mem_perc"]] = comp_instances
            for vm, info in comp_instances.items():
                refresh_instance_database(comp_info, vm, info)

        conn.close()
    else:
        raise libvirtError(_(f"Problem occurred with host: {comp.name} - {status}"))
    return all_host_vms


def get_user_instances(request):
    all_user_vms = {}
    user_instances = UserInstance.objects.filter(user_id=request.user.id)
    for usr_inst in user_instances:
        if connection_manager.host_is_up(usr_inst.instance.compute.type,
                                         usr_inst.instance.compute.hostname):
            conn = wvmHostDetails(usr_inst.instance.compute.hostname,
                                  usr_inst.instance.compute.login,
                                  usr_inst.instance.compute.password,
                                  usr_inst.instance.compute.type)
            all_user_vms[usr_inst] = conn.get_user_instances(usr_inst.instance.name)
            all_user_vms[usr_inst].update({'compute_id': usr_inst.instance.compute.id})
    return all_user_vms


def instances_actions(request):
    name = request.POST.get('name', '')
    compute_id = request.POST.get('compute_id', '')
    instance = Instance.objects.get(compute_id=compute_id, name=name)

    conn = wvmInstances(instance.compute.hostname,
                        instance.compute.login,
                        instance.compute.password,
                        instance.compute.type)
    if 'poweron' in request.POST:
        if instance.is_template:
            msg = _("Templates cannot be started.")
            messages.error(request, msg)
        else:
            msg = _("Power On")
            addlogmsg(request.user.username, instance.name, msg)
            conn.start(name)
            return HttpResponseRedirect(request.get_full_path())

    if 'poweroff' in request.POST:
        msg = _("Power Off")
        addlogmsg(request.user.username, instance.name, msg)
        conn.shutdown(name)
        return HttpResponseRedirect(request.get_full_path())

    if 'powerforce' in request.POST:
        conn.force_shutdown(name)
        msg = _("Force Off")
        addlogmsg(request.user.username, instance.name, msg)
        return HttpResponseRedirect(request.get_full_path())

    if 'powercycle' in request.POST:
        msg = _("Power Cycle")
        conn.force_shutdown(name)
        conn.start(name)
        addlogmsg(request.user.username, instance.name, msg)
        return HttpResponseRedirect(request.get_full_path())

    if 'getvvfile' in request.POST:
        msg = _("Send console.vv file")
        addlogmsg(request.user.username, instance.name, msg)
        response = HttpResponse(content='', content_type='application/x-virt-viewer', status=200, reason=None,
                                charset='utf-8')
        response.writelines('[virt-viewer]\n')
        response.writelines('type=' + conn.graphics_type(name) + '\n')
        response.writelines('host=' + conn.graphics_listen(name) + '\n')
        response.writelines('port=' + conn.graphics_port(name) + '\n')
        response.writelines('title=' + conn.domain_name(name) + '\n')
        response.writelines('password=' + conn.graphics_passwd(name) + '\n')
        response.writelines('enable-usbredir=1\n')
        response.writelines('disable-effects=all\n')
        response.writelines('secure-attention=ctrl+alt+ins\n')
        response.writelines('release-cursor=ctrl+alt\n')
        response.writelines('fullscreen=1\n')
        response.writelines('delete-this-file=1\n')
        response['Content-Disposition'] = 'attachment; filename="console.vv"'
        return response

    if request.user.is_superuser:
        if 'suspend' in request.POST:
            msg = _("Suspend")
            addlogmsg(request.user.username, instance.name, msg)
            conn.suspend(name)
            return HttpResponseRedirect(request.get_full_path())

        if 'resume' in request.POST:
            msg = _("Resume")
            addlogmsg(request.user.username, instance.name, msg)
            conn.resume(name)
            return HttpResponseRedirect(request.get_full_path())
    return HttpResponseRedirect(request.get_full_path())


def inst_graph(request, compute_id, vname):
    """
    :param request:
    :param compute_id:
    :param vname:
    :return:
    """
    json_blk = []
    json_net = []

    compute = get_object_or_404(Compute, pk=compute_id)
    response = HttpResponse()
    response['Content-Type'] = "text/javascript"

    try:
        conn = wvmInstance(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type,
                           vname)
        cpu_usage = conn.cpu_usage()
        mem_usage = conn.mem_usage()
        blk_usage = conn.disk_usage()
        net_usage = conn.net_usage()
        conn.close()

        current_time = time.strftime("%H:%M:%S")
        for blk in blk_usage:
            json_blk.append({'dev': blk['dev'], 'data': [int(blk['rd']) / 1048576, int(blk['wr']) / 1048576]})

        for net in net_usage:
            json_net.append({'dev': net['dev'], 'data': [int(net['rx']) / 1048576, int(net['tx']) / 1048576]})

        data = json.dumps({'cpudata': int(cpu_usage['cpu']),
                           'memdata': mem_usage,
                           'blkdata': json_blk,
                           'netdata': json_net,
                           'timeline': current_time})

    except libvirtError:
        data = json.dumps({'error': 'Error 500'})

    response.write(data)
    return response


def _get_dhcp_mac_address(vname):

    dhcp_file = settings.BASE_DIR + '/dhcpd.conf'
    mac = ''
    if os.path.isfile(dhcp_file):
        with open(dhcp_file, 'r') as f:
            name_found = False
            for line in f:
                if "host %s." % vname in line:
                    name_found = True
                if name_found and "hardware ethernet" in line:
                    mac = line.split(' ')[-1].strip().strip(';')
                    break
    return mac


def guess_mac_address(request, vname):
    data = {'vname': vname}
    mac = _get_dhcp_mac_address(vname)
    if not mac:
        mac = _get_random_mac_address()
    data['mac'] = mac
    return HttpResponse(json.dumps(data))


def _get_random_mac_address():
    mac = '52:54:00:%02x:%02x:%02x' % (
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff)
    )
    return mac


def random_mac_address(request):
    data = dict()
    data['mac'] = _get_random_mac_address()
    return HttpResponse(json.dumps(data))


def guess_clone_name(request):
    dhcp_file = '/srv/webvirtcloud/dhcpd.conf'
    prefix = appsettings.get(key="CLONE_INSTANCE_DEFAULT_PREFIX").value
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


def get_clone_disk_name(disk, prefix, clone_name=''):
    if not disk['image']:
        return None
    if disk['image'].startswith(prefix) and clone_name:
        suffix = disk['image'][len(prefix):]
        image = f"{clone_name}{suffix}"
    elif "." in disk['image'] and len(disk['image'].rsplit(".", 1)[1]) <= 7:
        name, suffix = disk['image'].rsplit(".", 1)
        image = f"{name}-clone.{suffix}"
    else:
        image = f"{disk['image']}-clone"
    return image


def _get_clone_disks(disks, vname=''):
    clone_disks = []
    for disk in disks:
        new_image = get_clone_disk_name(disk, vname)
        if not new_image:
            continue
        new_disk = {
            'dev': disk['dev'],
            'storage': disk['storage'],
            'image': new_image,
            'format': disk['format']
        }
        clone_disks.append(new_disk)
    return clone_disks


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
                                 'details': compute.details
                                 })
        return compute_data


def delete_instance(instance, delete_disk=False):
    compute = instance.compute
    instance_name = instance.name
    try:
        conn = wvmInstance(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type,
                           instance.name)

        del_userinstance = UserInstance.objects.filter(instance=instance)
        if del_userinstance:
            print("Deleting user instances")
            print(del_userinstance)
            del_userinstance.delete()

        if conn.get_status() == 1:
            print("Forcing shutdown")
            conn.force_shutdown()
        if delete_disk:
            snapshots = sorted(conn.get_snapshot(), reverse=True, key=lambda k: k['date'])
            for snap in snapshots:
                print("Deleting snapshot {}".format(snap['name']))
                conn.snapshot_delete(snap['name'])
            print("Deleting disks")
            conn.delete_all_disks()

        conn.delete()
        instance.delete()

        print(f"Instance {instance_name} on compute {compute.hostname} successfully deleted")

    except libvirtError as lib_err:
        print(f"Error removing instance {instance_name} on compute {compute.hostname}")
        raise lib_err
