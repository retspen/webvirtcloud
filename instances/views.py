import os
import time
import json
import socket
import crypt
import re
import string
from random import choice
from bisect import insort
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.shortcuts import render, get_object_or_404
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.decorators import login_required
from computes.models import Compute
from instances.models import Instance
from django.contrib.auth.models import User
from accounts.models import UserInstance, UserSSHKey
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.connection import connection_manager
from vrtManager.create import wvmCreate
from vrtManager.util import randomPasswd
from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE
from logs.views import addlogmsg
from django.conf import settings


@login_required
def index(request):
    """
    :param request:
    :return:
    """

    return HttpResponseRedirect(reverse('instances'))


@login_required
def instances(request):
    """
    :param request:
    :return:
    """

    error_messages = []
    all_host_vms = {}
    all_user_vms = {}
    computes = Compute.objects.all()

    def get_userinstances_info(instance):
        info = {}
        uis = UserInstance.objects.filter(instance=instance)
        info['count'] = uis.count()
        if info['count'] > 0:
            info['first_user'] = uis[0]
        else:
            info['first_user'] = None
        return info

    def refresh_instance_database(comp, vm, info):
        instances = Instance.objects.filter(name=vm)
        if instances.count() > 1:
            for i in instances:
                user_instances_count = UserInstance.objects.filter(instance=i).count()
                if user_instances_count == 0:
                    addlogmsg(request.user.username, i.name, _("Deleting due to multiple records."))
                    i.delete()
        
        try:
            check_uuid = Instance.objects.get(compute_id=comp["id"], name=vm)
            if check_uuid.uuid != info['uuid']:
                check_uuid.save()

            all_host_vms[comp_info["id"],
                         comp_info["name"],
                         comp_info["status"],
                         comp_info["cpu"],
                         comp_info["mem_size"],
                         comp_info["mem_perc"]][vm]['is_template'] = check_uuid.is_template
            all_host_vms[comp_info["id"],
                         comp_info["name"],
                         comp_info["status"],
                         comp_info["cpu"],
                         comp_info["mem_size"],
                         comp_info["mem_perc"]][vm]['userinstances'] = get_userinstances_info(check_uuid)
        except Instance.DoesNotExist:
            check_uuid = Instance(compute_id=comp["id"], name=vm, uuid=info['uuid'])
            check_uuid.save()
    
    if not request.user.is_superuser:
        user_instances = UserInstance.objects.filter(user_id=request.user.id)
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
            status = connection_manager.host_is_up(comp.type, comp.hostname)
            if status:
                try:
                    conn = wvmHostDetails(comp, comp.login, comp.password, comp.type)
                    comp_node_info = conn.get_node_info()
                    comp_mem = conn.get_memory_usage()
                    comp_instances = conn.get_host_instances(True)

                    if comp_instances:
                        comp_info= {
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
                except libvirtError as lib_err:
                    error_messages.append(lib_err)

    if request.method == 'POST':
        name = request.POST.get('name', '')
        compute_id = request.POST.get('compute_id', '')
        instance = Instance.objects.get(compute_id=compute_id, name=name)
        try:
            conn = wvmInstances(instance.compute.hostname,
                                instance.compute.login,
                                instance.compute.password,
                                instance.compute.type)
            if 'poweron' in request.POST:
                msg = _("Power On")
                addlogmsg(request.user.username, instance.name, msg)
                conn.start(name)
                return HttpResponseRedirect(request.get_full_path())

            if 'poweroff' in request.POST:
                msg = _("Power Off")
                addlogmsg(request.user.username, instance.name, msg)
                conn.shutdown(name)
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
                response = HttpResponse(content='', content_type='application/x-virt-viewer', status=200, reason=None, charset='utf-8')
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

        except libvirtError as lib_err:
            error_messages.append(lib_err)
            addlogmsg(request.user.username, instance.name, lib_err.message)

    return render(request, 'instances.html', locals())


@login_required
def instance(request, compute_id, vname):
    """
    :param request:
    :return:
    """

    error_messages = []
    messages = []
    compute = get_object_or_404(Compute, pk=compute_id)
    computes = Compute.objects.all().order_by('name')
    computes_count = computes.count()
    users = User.objects.all().order_by('username')
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)
    keymaps = settings.QEMU_KEYMAPS
    console_types = settings.QEMU_CONSOLE_TYPES
    console_listen_addresses = settings.QEMU_CONSOLE_LISTEN_ADDRESSES
    try:
        userinstace = UserInstance.objects.get(instance__compute_id=compute_id,
                                               instance__name=vname,
                                               user__id=request.user.id)
    except UserInstance.DoesNotExist:
        userinstace = None

    if not request.user.is_superuser:
        if not userinstace:
            return HttpResponseRedirect(reverse('index'))

    def show_clone_disk(disks, vname=''):
        clone_disk = []
        for disk in disks:
            if disk['image'] is None:
                continue
            if disk['image'].count("-") and disk['image'].rsplit("-", 1)[0] == vname:
                name, suffix = disk['image'].rsplit("-", 1)
                image = name + "-clone" + "-" + suffix
            elif disk['image'].count(".") and len(disk['image'].rsplit(".", 1)[1]) <= 7:
                name, suffix = disk['image'].rsplit(".", 1)
                image = name + "-clone" + "." + suffix
            else:
                image = disk['image'] + "-clone"
            clone_disk.append(
                {'dev': disk['dev'], 'storage': disk['storage'],
                 'image': image, 'format': disk['format']})
        return clone_disk
    
    def filesizefstr(size_str):
        if size_str == '':
            return 0
        size_str = size_str.encode('ascii', 'ignore').upper().translate(None, " B")
        if 'K' == size_str[-1]:
            return long(float(size_str[:-1]))<<10
        elif 'M' == size_str[-1]:
            return long(float(size_str[:-1]))<<20
        elif 'G' == size_str[-1]:
            return long(float(size_str[:-1]))<<30
        elif 'T' == size_str[-1]:
            return long(float(size_str[:-1]))<<40
        elif 'P' == size_str[-1]:
            return long(float(size_str[:-1]))<<50
        else:
            return long(float(size_str))

    def get_clone_free_names(size=10):
        prefix = settings.CLONE_INSTANCE_DEFAULT_PREFIX
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
        user_instances = UserInstance.objects.filter(user_id=request.user.id, instance__is_template=False)
        instance += user_instances.count()
        for usr_inst in user_instances:
            if connection_manager.host_is_up(usr_inst.instance.compute.type,
                                             usr_inst.instance.compute.hostname):
                conn = wvmInstance(usr_inst.instance.compute,
                                      usr_inst.instance.compute.login,
                                      usr_inst.instance.compute.password,
                                      usr_inst.instance.compute.type,
                                      usr_inst.instance.name)
                cpu += int(conn.get_vcpu())
                memory += int(conn.get_memory())
                for disk in conn.get_disk_device():
                    if disk['size']:
                        disk_size += int(disk['size'])>>30
        
        ua = request.user.userattributes
        msg = ""
        if ua.max_instances > 0 and instance > ua.max_instances:
            msg = "instance"
            if settings.QUOTA_DEBUG:
                msg += " (%s > %s)" % (instance, ua.max_instances)
        if ua.max_cpus > 0 and cpu > ua.max_cpus:
            msg = "cpu"
            if settings.QUOTA_DEBUG:
                msg += " (%s > %s)" % (cpu, ua.max_cpus)
        if ua.max_memory > 0 and memory > ua.max_memory:
            msg = "memory"
            if settings.QUOTA_DEBUG:
                msg += " (%s > %s)" % (memory, ua.max_memory)
        if ua.max_disk_size > 0 and disk_size > ua.max_disk_size:
            msg = "disk"
            if settings.QUOTA_DEBUG:
                msg += " (%s > %s)" % (disk_size, ua.max_disk_size)
        return msg

    def get_new_disk_dev(disks, bus):
        if bus == "virtio":
            dev_base = "vd"
        else:
            dev_base = "sd"
        existing_devs = [ disk['dev'] for disk in disks ]
        for l in string.lowercase:
            dev = dev_base + l
            if dev not in existing_devs:
                return dev
        raise Exception(_('None available device name'))
            
    try:
        conn = wvmInstance(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type,
                           vname)
        
        status = conn.get_status()
        autostart = conn.get_autostart()
        vcpu = conn.get_vcpu()
        cur_vcpu = conn.get_cur_vcpu()
        uuid = conn.get_uuid()
        memory = conn.get_memory()
        cur_memory = conn.get_cur_memory()
        title = conn.get_title()
        description = conn.get_description()
        disks = conn.get_disk_device()
        media = conn.get_media_device()
        networks = conn.get_net_device()
        if len(media) != 0:
            media_iso = sorted(conn.get_iso_media())
        else:
            media_iso = []
        vcpu_range = conn.get_max_cpus()
        memory_range = [256, 512, 768, 1024, 2048, 4096, 6144, 8192, 16384]
        if memory not in memory_range:
            insort(memory_range, memory)
        if cur_memory not in memory_range:
            insort(memory_range, cur_memory)
        memory_host = conn.get_max_memory()
        vcpu_host = len(vcpu_range)
        telnet_port = conn.get_telnet_port()
        console_type = conn.get_console_type()
        console_port = conn.get_console_port()
        console_keymap = conn.get_console_keymap()
        snapshots = sorted(conn.get_snapshot(), reverse=True, key=lambda k:k['date'])
        inst_xml = conn._XMLDesc(VIR_DOMAIN_XML_SECURE)
        has_managed_save_image = conn.get_managed_save_image()
        clone_disks = show_clone_disk(disks, vname)
        console_passwd = conn.get_console_passwd()
        clone_free_names = get_clone_free_names()
        user_quota_msg = check_user_quota(0, 0, 0, 0)
        storages = sorted(conn.get_storages())
        cache_modes = sorted(conn.get_cache_modes().items())
        default_cache = settings.INSTANCE_VOLUME_DEFAULT_CACHE
        default_format = settings.INSTANCE_VOLUME_DEFAULT_FORMAT
        formats = conn.get_image_formats()
        default_bus = settings.INSTANCE_VOLUME_DEFAULT_BUS
        busses = conn.get_busses()
        default_bus = settings.INSTANCE_VOLUME_DEFAULT_BUS
        show_access_root_password = settings.SHOW_ACCESS_ROOT_PASSWORD
        show_access_ssh_keys = settings.SHOW_ACCESS_SSH_KEYS

        try:
            instance = Instance.objects.get(compute_id=compute_id, name=vname)
            if instance.uuid != uuid:
                instance.uuid = uuid
                instance.save()
        except Instance.DoesNotExist:
            instance = Instance(compute_id=compute_id, name=vname, uuid=uuid)
            instance.save()

        userinstances = UserInstance.objects.filter(instance=instance).order_by('user__username')

        if request.method == 'POST':
            if 'poweron' in request.POST:
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

            if 'delete' in request.POST and (request.user.is_superuser or userinstace.is_delete):
                if conn.get_status() == 1:
                    conn.force_shutdown()
                if request.POST.get('delete_disk', ''):
                    for snap in snapshots:
                        conn.snapshot_delete(snap['name'])
                    conn.delete_disk()
                conn.delete()

                instance = Instance.objects.get(compute_id=compute_id, name=vname)
                instance_name = instance.name
                instance.delete()

                try:
                    del_userinstance = UserInstance.objects.filter(instance__compute_id=compute_id, instance__name=vname)
                    del_userinstance.delete()
                except UserInstance.DoesNotExist:
                    pass

                msg = _("Destroy")
                addlogmsg(request.user.username, instance_name, msg)

                return HttpResponseRedirect(reverse('instances'))

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
                        messages.append(msg)
                    else:
                        error_messages.append(msg)
                else:
                    msg = _("Please shutdow down your instance and then try again")
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
                    msg = _("Installed new ssh public key %s" % publickey.keyname)
                    addlogmsg(request.user.username, instance.name, msg)

                    if result['return'] == 'success':
                        messages.append(msg)
                    else:
                        error_messages.append(msg)
                else:
                    msg = _("Please shutdow down your instance and then try again")
                    error_messages.append(msg)

            if 'resize' in request.POST and (request.user.is_superuser or request.user.is_staff or userinstace.is_change):
                new_vcpu = request.POST.get('vcpu', '')
                new_cur_vcpu = request.POST.get('cur_vcpu', '')
                new_memory = request.POST.get('memory', '')
                new_memory_custom = request.POST.get('memory_custom', '')
                if new_memory_custom:
                    new_memory = new_memory_custom
                new_cur_memory = request.POST.get('cur_memory', '')
                new_cur_memory_custom = request.POST.get('cur_memory_custom', '')
                if new_cur_memory_custom:
                    new_cur_memory = new_cur_memory_custom
                disks_new = []
                for disk in disks:
                    input_disk_size = filesizefstr(request.POST.get('disk_size_' + disk['dev'], ''))
                    if input_disk_size > disk['size']+(64<<20):
                        disk['size_new'] = input_disk_size
                        disks_new.append(disk) 
                disk_sum = sum([disk['size']>>30 for disk in disks_new])
                disk_new_sum = sum([disk['size_new']>>30 for disk in disks_new])
                quota_msg = check_user_quota(0, int(new_vcpu)-vcpu, int(new_memory)-memory, disk_new_sum-disk_sum)
                if not request.user.is_superuser and quota_msg:    
                    msg = _("User %s quota reached, cannot resize '%s'!" % (quota_msg, instance.name))
                    error_messages.append(msg)
                else:
                    cur_memory = new_cur_memory
                    memory = new_memory
                    cur_vcpu = new_cur_vcpu
                    vcpu = new_vcpu
                    conn.resize(cur_memory, memory, cur_vcpu, vcpu, disks_new)
                    msg = _("Resize")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#resize')

            if 'addvolume' in request.POST and (request.user.is_superuser or userinstace.is_change):
                connCreate = wvmCreate(compute.hostname,
                                   compute.login,
                                   compute.password,
                                   compute.type)
                storage = request.POST.get('storage', '')
                name = request.POST.get('name', '')
                extension = request.POST.get('extension', '')
                format = request.POST.get('format', '')
                size = request.POST.get('size', 0)
                meta_prealloc = request.POST.get('meta_prealloc', False)
                bus = request.POST.get('bus', '')
                cache = request.POST.get('cache', '')
                target = get_new_disk_dev(disks, bus)
                
                path = connCreate.create_volume(storage, name, size, format, meta_prealloc, extension)
                conn.attach_disk(path, target, subdriver=format, cache=cache, targetbus=bus)
                msg = _('Attach new disk')
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#resize')

            if 'umount_iso' in request.POST:
                image = request.POST.get('path', '')
                dev = request.POST.get('umount_iso', '')
                conn.umount_iso(dev, image)
                msg = _("Mount media")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#media')

            if 'mount_iso' in request.POST:
                image = request.POST.get('media', '')
                dev = request.POST.get('mount_iso', '')
                conn.mount_iso(dev, image)
                msg = _("Umount media")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#media')

            if 'snapshot' in request.POST:
                name = request.POST.get('name', '')
                conn.create_snapshot(name)
                msg = _("New snapshot")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#restoresnapshot')

            if 'delete_snapshot' in request.POST:
                snap_name = request.POST.get('name', '')
                conn.snapshot_delete(snap_name)
                msg = _("Delete snapshot")
                addlogmsg(request.user.username, instance.name, msg)
                return HttpResponseRedirect(request.get_full_path() + '#restoresnapshot')

            if 'revert_snapshot' in request.POST:
                snap_name = request.POST.get('name', '')
                conn.snapshot_revert(snap_name)
                msg = _("Successful revert snapshot: ")
                msg += snap_name
                messages.append(msg)
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

                if 'set_autostart' in request.POST:
                    conn.set_autostart(1)
                    msg = _("Set autostart")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#autostart')

                if 'unset_autostart' in request.POST:
                    conn.set_autostart(0)
                    msg = _("Unset autostart")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#autostart')

                if 'change_xml' in request.POST:
                    exit_xml = request.POST.get('inst_xml', '')
                    if exit_xml:
                        conn._defineXML(exit_xml)
                        msg = _("Edit XML")
                        addlogmsg(request.user.username, instance.name, msg)
                        return HttpResponseRedirect(request.get_full_path() + '#xmledit')

            if request.user.is_superuser or userinstace.is_vnc:
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
                            msg = _("Error setting console password. You should check that your instance have an graphic device.")
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
                    conn.set_console_type(console_type)
                    msg = _("Set VNC type")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#vncsettings')
                
                if 'set_console_listen_address' in request.POST:
                    console_type = request.POST.get('console_listen_address', '')
                    conn.set_console_listen_addr(console_type)
                    msg = _("Set VNC listen address")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#vncsettings')

            if request.user.is_superuser:
                if 'migrate' in request.POST:
                    compute_id = request.POST.get('compute_id', '')
                    live = request.POST.get('live_migrate', False)
                    unsafe = request.POST.get('unsafe_migrate', False)
                    xml_del = request.POST.get('xml_delete', False)
                    offline = request.POST.get('offline_migrate', False)
                    new_compute = Compute.objects.get(id=compute_id)
                    conn_migrate = wvmInstances(new_compute.hostname,
                                                new_compute.login,
                                                new_compute.password,
                                                new_compute.type)
                    conn_migrate.moveto(conn, vname, live, unsafe, xml_del, offline)
                    instance.compute = new_compute
                    instance.save()
                    conn_migrate.close()
                    if autostart:
                        conn_new = wvmInstance(new_compute.hostname,
                                               new_compute.login,
                                               new_compute.password,
                                               new_compute.type,
                                               vname)
                        conn_new.set_autostart(1)
                        conn_new.close()
                    msg = _("Migrate to %s" % new_compute.hostname)
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(reverse('instance', args=[compute_id, vname]))

                if 'change_network' in request.POST:
                    network_data = {}

                    for post in request.POST:
                        if post.startswith('net-'):
                            network_data[post] = request.POST.get(post, '')

                    conn.change_network(network_data)
                    msg = _("Edit network")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#network')

                if 'add_owner' in request.POST:
                    user_id = int(request.POST.get('user_id', ''))
                    
                    if settings.ALLOW_INSTANCE_MULTIPLE_OWNER:
                        check_inst = UserInstance.objects.filter(instance=instance, user_id=user_id)
                    else:
                        check_inst = UserInstance.objects.filter(instance=instance)
                    
                    if check_inst:
                        msg = _("Owner already added")
                        error_messages.append(msg)
                    else:
                        add_user_inst = UserInstance(instance=instance, user_id=user_id)
                        add_user_inst.save()
                        msg = _("Added owner %d" % user_id)
                        addlogmsg(request.user.username, instance.name, msg)
                        return HttpResponseRedirect(request.get_full_path() + '#users')

                if 'del_owner' in request.POST:
                    userinstance_id = int(request.POST.get('userinstance', ''))
                    userinstance = UserInstance.objects.get(pk=userinstance_id)
                    userinstance.delete()
                    msg = _("Deleted owner %d" % userinstance_id)
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(request.get_full_path() + '#users')


            if request.user.is_superuser or request.user.userattributes.can_clone_instances:
                if 'clone' in request.POST:
                    clone_data = {}
                    clone_data['name'] = request.POST.get('name', '')

                    disk_sum = sum([disk['size']>>30 for disk in disks])
                    quota_msg = check_user_quota(1, vcpu, memory, disk_sum)
                    check_instance = Instance.objects.filter(name=clone_data['name'])
                    
                    for post in request.POST:
                        clone_data[post] = request.POST.get(post, '').strip()
                    
                    if not request.user.is_superuser and quota_msg:
                        msg = _("User %s quota reached, cannot create '%s'!" % (quota_msg, clone_data['name']))
                        error_messages.append(msg)
                    elif check_instance:
                        msg = _("Instance '%s' already exists!" % clone_data['name'])
                        error_messages.append(msg)
                    elif not re.match(r'^[a-zA-Z0-9-]+$', clone_data['name']):
                        msg = _("Instance name '%s' contains invalid characters!" % clone_data['name'])
                        error_messages.append(msg)
                    elif not re.match(r'^([0-9A-F]{2})(\:?[0-9A-F]{2}){5}$', clone_data['clone-net-mac-0'], re.IGNORECASE):
                        msg = _("Instance mac '%s' invalid format!" % clone_data['clone-net-mac-0'])
                        error_messages.append(msg)
                    else:
                        new_uuid = conn.clone_instance(clone_data)
                        new_instance = Instance(compute_id=compute_id, name=clone_data['name'], uuid=new_uuid)
                        new_instance.save()
                        userinstance = UserInstance(instance_id=new_instance.id, user_id=request.user.id, is_delete=True)
                        userinstance.save()

                        msg = _("Clone of '%s'" % instance.name)
                        addlogmsg(request.user.username, new_instance.name, msg)
                        return HttpResponseRedirect(reverse('instance', args=[compute_id, clone_data['name']]))

                if 'change_options' in request.POST:
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
        error_messages.append(lib_err.message)
        addlogmsg(request.user.username, vname, lib_err.message)

    return render(request, 'instance.html', locals())


@login_required
def inst_status(request, compute_id, vname):
    """
    :param request:
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


@login_required
def inst_graph(request, compute_id, vname):
    """
    :param request:
    :return:
    """

    datasets = {}
    json_blk = []
    datasets_blk = {}
    json_net = []
    datasets_net = {}
    cookies = {}
    points = 5
    curent_time = time.strftime("%H:%M:%S")
    compute = get_object_or_404(Compute, pk=compute_id)
    response = HttpResponse()
    response['Content-Type'] = "text/javascript"

    def check_points(dataset):
        if len(dataset) > points:
            dataset.pop(0)
        return dataset

    try:
        conn = wvmInstance(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type,
                           vname)
        cpu_usage = conn.cpu_usage()
        blk_usage = conn.disk_usage()
        net_usage = conn.net_usage()
        conn.close()

        try:
            cookies['cpu'] = request.COOKIES['cpu']
            cookies['blk'] = request.COOKIES['blk']
            cookies['net'] = request.COOKIES['net']
            cookies['timer'] = request.COOKIES['timer']
        except KeyError:
            cookies['cpu'] = None
            cookies['blk'] = None
            cookies['net'] = None

        if not cookies['cpu']:
            datasets['cpu'] = [0] * points
            datasets['timer'] = [0] * points
        else:
            datasets['cpu'] = eval(cookies['cpu'])
            datasets['timer'] = eval(cookies['timer'])

        datasets['timer'].append(curent_time)
        datasets['cpu'].append(int(cpu_usage['cpu']))

        datasets['timer'] = check_points(datasets['timer'])
        datasets['cpu'] = check_points(datasets['cpu'])

        for blk in blk_usage:
            if not cookies['blk']:
                datasets_wr = [0] * points
                datasets_rd = [0] * points
            else:
                datasets['blk'] = eval(cookies['blk'])
                datasets_rd = datasets['blk'][blk['dev']][0]
                datasets_wr = datasets['blk'][blk['dev']][1]

                datasets_rd.append(int(blk['rd']) / 1048576)
                datasets_wr.append(int(blk['wr']) / 1048576)

                datasets_rd = check_points(datasets_rd)
                datasets_wr = check_points(datasets_wr)

            json_blk.append({'dev': blk['dev'], 'data': [datasets_rd, datasets_wr]})
            datasets_blk[blk['dev']] = [datasets_rd, datasets_wr]

        for net in net_usage:
            if not cookies['net']:
                datasets_rx = [0] * points
                datasets_tx = [0] * points
            else:
                datasets['net'] = eval(cookies['net'])
                datasets_rx = datasets['net'][net['dev']][0]
                datasets_tx = datasets['net'][net['dev']][1]

                datasets_rx.append(int(net['rx']) / 1048576)
                datasets_tx.append(int(net['tx']) / 1048576)

                datasets_rx = check_points(datasets_rx)
                datasets_tx = check_points(datasets_tx)

            json_net.append({'dev': net['dev'], 'data': [datasets_rx, datasets_tx]})
            datasets_net[net['dev']] = [datasets_rx, datasets_tx]

        data = json.dumps({'cpudata': datasets['cpu'], 'blkdata': json_blk,
                           'netdata': json_net, 'timeline': datasets['timer']})

        response.cookies['cpu'] = datasets['cpu']
        response.cookies['timer'] = datasets['timer']
        response.cookies['blk'] = datasets_blk
        response.cookies['net'] = datasets_net
    except libvirtError:
        data = json.dumps({'error': 'Error 500'})

    response.write(data)
    return response

@login_required
def guess_mac_address(request, vname):
    dhcp_file = '/srv/webvirtcloud/dhcpd.conf'
    data = { 'vname': vname, 'mac': '52:54:00:' }
    if os.path.isfile(dhcp_file):
        with open(dhcp_file, 'r') as f:
            name_found = False
            for line in f:
                if "host %s." % vname in line:
                    name_found = True
                if name_found and "hardware ethernet" in line:
                    data['mac'] = line.split(' ')[-1].strip().strip(';')
                    break
    return HttpResponse(json.dumps(data))

@login_required
def guess_clone_name(request):
    dhcp_file = '/srv/webvirtcloud/dhcpd.conf'
    prefix = settings.CLONE_INSTANCE_DEFAULT_PREFIX
    if os.path.isfile(dhcp_file):
        instance_names = [i.name for i in Instance.objects.filter(name__startswith=prefix)]
        with open(dhcp_file, 'r') as f:
            for line in f:
                line = line.strip()
                if "host %s" % prefix in line:
                    fqdn = line.split(' ')[1]
                    hostname = fqdn.split('.')[0]
                    if hostname.startswith(prefix) and hostname not in instance_names:
                        return HttpResponse(json.dumps({'name': hostname}))
    return HttpResponse(json.dumps({}))

@login_required
def check_instance(request, vname):
    check_instance = Instance.objects.filter(name=vname)
    data = { 'vname': vname, 'exists': False }
    if check_instance:
        data['exists'] = True
    return HttpResponse(json.dumps(data))

def sshkeys(request, vname):
    """
    :param request:
    :param vm:
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
            print("Deleting UserInstances")
            print(del_userinstance)
            del_userinstance.delete()

        if conn.get_status() == 1:
            print("Forcing shutdown")
            conn.force_shutdown()
        if delete_disk:
            snapshots = sorted(conn.get_snapshot(), reverse=True, key=lambda k:k['date'])
            for snap in snapshots:
                print("Deleting snapshot {}".format(snap['name']))
                conn.snapshot_delete(snap['name'])
            print("Deleting disks")
            conn.delete_disk()

        conn.delete()
        instance.delete()

        print("Instance {} on compute {} sucessfully deleted".format(instance_name, compute.hostname))

    except libvirtError as lib_err:
        print("Error removing instance {} on compute {}".format(instance_name, compute.hostname))
        raise lib_err

