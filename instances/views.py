import time
import json
from string import letters, digits
from random import choice
from bisect import insort
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.shortcuts import render
from django.utils.translation import ugettext_lazy as _
from computes.models import Compute
from instances.models import Instance
from accounts.models import UserInstance
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.connection import connection_manager
from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE
from webvirtcloud.settings import QEMU_KEYMAPS, QEMU_CONSOLE_TYPES
from logs.views import addlogmsg


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
        instance = Instance.objects.get(compute_id=compute_id, name=name)
        try:
            conn = wvmInstances(instance.compute.hostname,
                                instance.compute.login,
                                instance.compute.password,
                                instance.compute.type)
            if 'poweron' in request.POST:
                msg = _("Power On")
                addlogmsg(request.user.id, instance.id, msg)
                conn.start(name)
                return HttpResponseRedirect(request.get_full_path())
            if 'powercycle' in request.POST:
                msg = _("Power Cycle")
                conn.force_shutdown(name)
                conn.start()
                addlogmsg(request.user.id, instance.id, msg)
                return HttpResponseRedirect(request.get_full_path())
            if 'poweroff' in request.POST:
                msg = _("Power Off")
                addlogmsg(request.user.id, instance.id, msg)
                conn.shutdown(name)
                return HttpResponseRedirect(request.get_full_path())
            if request.user.is_superuser:
                if 'suspend' in request.POST:
                    msg = _("Suspend")
                    addlogmsg(request.user.id, instance.id, msg)
                    conn.suspend(name)
                    return HttpResponseRedirect(request.get_full_path())
                if 'resume' in request.POST:
                    msg = _("Resume")
                    addlogmsg(request.user.id, instance.id, msg)
                    conn.resume(name)
                    return HttpResponseRedirect(request.get_full_path())
        except libvirtError as lib_err:
            error_messages.append(lib_err)
            addlogmsg(request.user.id, instance.id, lib_err.message)

    return render(request, 'instances.html', locals())


def instance(request, compute_id, vname):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    error_messages = []
    messages = []
    compute = Compute.objects.get(id=compute_id)
    computes = Compute.objects.all()
    computes_count = len(computes)
    keymaps = QEMU_KEYMAPS
    console_types = QEMU_CONSOLE_TYPES
    try:
        userinstace = UserInstance.objects.get(instance__compute_id=compute_id,
                                               instance__name=vname,
                                               user__id=request.user.id)
    except UserInstance.DoesNotExist:
        userinstace = None

    if not request.user.is_superuser:
        if not userinstace:
            return HttpResponseRedirect(reverse('index'))

    def show_clone_disk(disks):
        clone_disk = []
        for disk in disks:
            if disk['image'] is None:
                continue
            if disk['image'].count(".") and len(disk['image'].rsplit(".", 1)[1]) <= 7:
                name, suffix = disk['image'].rsplit(".", 1)
                image = name + "-clone" + "." + suffix
            else:
                image = disk['image'] + "-clone"
            clone_disk.append(
                {'dev': disk['dev'], 'storage': disk['storage'], 'image': image, 'format': disk['format']})
        return clone_disk

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
        description = conn.get_description()
        disks = conn.get_disk_device()
        media = conn.get_media_device()
        networks = conn.get_net_device()
        media_iso = sorted(conn.get_iso_media())
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
        snapshots = sorted(conn.get_snapshot(), reverse=True)
        inst_xml = conn._XMLDesc(VIR_DOMAIN_XML_SECURE)
        has_managed_save_image = conn.get_managed_save_image()
        clone_disks = show_clone_disk(disks)
        console_passwd = conn.get_console_passwd()

        try:
            instance = Instance.objects.get(compute_id=compute_id, name=vname)
            if instance.uuid != uuid:
                instance.uuid = uuid
                instance.save()
        except Instance.DoesNotExist:
            instance = Instance(compute_id=compute_id, name=vname, uuid=uuid)
            instance.save()

        if request.method == 'POST':
            if 'poweron' in request.POST:
                msg = _("Power On")
                addlogmsg(request.user.id, instance.id, msg)
                conn.start()
                return HttpResponseRedirect(request.get_full_path() + '#poweron')

            if 'powercycle' in request.POST:
                msg = _("Power Cycle")
                addlogmsg(request.user.id, instance.id, msg)
                conn.force_shutdown()
                conn.start()
                return HttpResponseRedirect(request.get_full_path() + '#powercycle')

            if 'poweroff' == request.POST.get('power', ''):
                msg = _("Power Off")
                addlogmsg(request.user.id, instance.id, msg)
                conn.shutdown()
                return HttpResponseRedirect(request.get_full_path() + '#poweroff')

            if 'delete' in request.POST:
                msg = _("Destroy")
                addlogmsg(request.user.id, instance.id, msg)
                if conn.get_status() == 1:
                    conn.force_shutdown()
                try:
                    instance = Instance.objects.get(compute_id=compute_id, name=vname)
                    instance.delete()
                    if request.POST.get('delete_disk', ''):
                        conn.delete_disk()
                finally:
                    if not request.user.is_superuser:
                        del_userinstance = UserInstance.objects.get(id=userinstace.id)
                        del_userinstance.delete()
                    else:
                        try:
                            del_userinstance = UserInstance.objects.filter(instance__compute_id=compute_id, instance__name=vname)
                            del_userinstance.save()
                        except UserInstance.DoesNotExist:
                            pass
                    conn.delete()
                return HttpResponseRedirect(reverse('instances'))

            if 'snapshot' in request.POST:
                msg = _("New snapshot")
                addlogmsg(request.user.id, instance.id, msg)
                name = request.POST.get('name', '')
                conn.create_snapshot(name)
                return HttpResponseRedirect(request.get_full_path() + '#istaceshapshosts')

            if 'umount_iso' in request.POST:
                msg = _("Mount media")
                addlogmsg(request.user.id, instance.id, msg)
                image = request.POST.get('path', '')
                dev = request.POST.get('umount_iso', '')
                conn.umount_iso(dev, image)
                return HttpResponseRedirect(request.get_full_path() + '#instancemedia')

            if 'mount_iso' in request.POST:
                msg = _("Umount media")
                addlogmsg(request.user.id, instance.id, msg)
                image = request.POST.get('media', '')
                dev = request.POST.get('mount_iso', '')
                conn.mount_iso(dev, image)
                return HttpResponseRedirect(request.get_full_path() + '#instancemedia')

            if 'delete_snapshot' in request.POST:
                msg = _("Delete snapshot")
                addlogmsg(request.user.id, instance.id, msg)
                snap_name = request.POST.get('name', '')
                conn.snapshot_delete(snap_name)
                return HttpResponseRedirect(request.get_full_path() + '#istaceshapshosts')

            if 'revert_snapshot' in request.POST:
                msg = _("Revert snapshot")
                addlogmsg(request.user.id, instance.id, msg)
                snap_name = request.POST.get('name', '')
                conn.snapshot_revert(snap_name)
                msg = _("Successful revert snapshot: ")
                msg += snap_name
                messages.append(msg)

            if request.user.is_superuser:
                if 'suspend' in request.POST:
                    msg = _("Suspend")
                    addlogmsg(request.user.id, instance.id, msg)
                    conn.suspend()
                    return HttpResponseRedirect(request.get_full_path() + '#resume')

                if 'resume' in request.POST:
                    msg = _("Resume")
                    addlogmsg(request.user.id, instance.id, msg)
                    conn.resume()
                    return HttpResponseRedirect(request.get_full_path() + '#suspend')

                if 'set_autostart' in request.POST:
                    msg = _("Set autostart")
                    addlogmsg(request.user.id, instance.id, msg)
                    conn.set_autostart(1)
                    return HttpResponseRedirect(request.get_full_path() + '#instancesettings')

                if 'unset_autostart' in request.POST:
                    msg = _("Unset autostart")
                    addlogmsg(request.user.id, instance.id, msg)
                    conn.set_autostart(0)
                    return HttpResponseRedirect(request.get_full_path() + '#instancesettings')

                if 'resize' in request.POST:
                    msg = _("Resize")
                    addlogmsg(request.user.id, instance.id, msg)
                    description = request.POST.get('description', '')
                    vcpu = request.POST.get('vcpu', '')
                    cur_vcpu = request.POST.get('cur_vcpu', '')
                    memory = request.POST.get('memory', '')
                    memory_custom = request.POST.get('memory_custom', '')
                    if memory_custom:
                        memory = memory_custom
                    cur_memory = request.POST.get('cur_memory', '')
                    cur_memory_custom = request.POST.get('cur_memory_custom', '')
                    if cur_memory_custom:
                        cur_memory = cur_memory_custom
                    conn.resize(cur_memory, memory, cur_vcpu, vcpu)
                    return HttpResponseRedirect(request.get_full_path() + '#instancesettings')

                if 'change_xml' in request.POST:
                    msg = _("Edit XML")
                    addlogmsg(request.user.id, instance.id, msg)
                    exit_xml = request.POST.get('inst_xml', '')
                    if exit_xml:
                        conn._defineXML(exit_xml)
                        return HttpResponseRedirect(request.get_full_path() + '#instancexml')

                if 'set_console_passwd' in request.POST:
                    msg = _("Set VNC password")
                    addlogmsg(request.user.id, instance.id, msg)
                    if request.POST.get('auto_pass', ''):
                        passwd = ''.join([choice(letters + digits) for i in xrange(12)])
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
                            return HttpResponseRedirect(request.get_full_path() + '#console_pass')

                if 'set_console_keymap' in request.POST:
                    msg = _("Set VNC keymap")
                    addlogmsg(request.user.id, instance.id, msg)
                    keymap = request.POST.get('console_keymap', '')
                    clear = request.POST.get('clear_keymap', False)
                    if clear:
                        conn.set_console_keymap('')
                    else:
                        conn.set_console_keymap(keymap)
                    return HttpResponseRedirect(request.get_full_path() + '#console_keymap')

                if 'set_console_type' in request.POST:
                    msg = _("Set VNC type")
                    addlogmsg(request.user.id, instance.id, msg)
                    console_type = request.POST.get('console_type', '')
                    conn.set_console_type(console_type)
                    return HttpResponseRedirect(request.get_full_path() + '#console_type')

                if 'migrate' in request.POST:
                    msg = _("Migrate")
                    addlogmsg(request.user.id, instance.id, msg)
                    compute_id = request.POST.get('compute_id', '')
                    live = request.POST.get('live_migrate', False)
                    unsafe = request.POST.get('unsafe_migrate', False)
                    xml_del = request.POST.get('xml_delete', False)
                    new_compute = Compute.objects.get(id=compute_id)
                    conn_migrate = wvmInstances(new_compute.hostname,
                                                new_compute.login,
                                                new_compute.password,
                                                new_compute.type)
                    conn_migrate.moveto(conn, vname, live, unsafe, xml_del)
                    conn_migrate.define_move(vname)
                    conn_migrate.close()
                    return HttpResponseRedirect(reverse('instance', args=[compute_id, vname]))

                if 'clone' in request.POST:
                    msg = _("Clone")
                    addlogmsg(request.user.id, instance.id, msg)
                    clone_data = {}
                    clone_data['name'] = request.POST.get('name', '')

                    for post in request.POST:
                        if 'disk' or 'meta' in post:
                            clone_data[post] = request.POST.get(post, '')

                    conn.clone_instance(clone_data)
                    return HttpResponseRedirect(reverse('instance', args=[compute_id, clone_data['name']]))

        conn.close()

    except libvirtError as lib_err:
        error_messages.append(lib_err.message)
        addlogmsg(request.user.id, instance.id, lib_err.message)

    return render(request, 'instance.html', locals())


def inst_graph(request, compute_id, vname):
    """
    Return instance usage
    """
    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('login'))

    datasets = {}
    datasets_rd = []
    datasets_wr = []
    json_blk = []
    cookie_blk = {}
    blk_error = False
    datasets_rx = []
    datasets_tx = []
    json_net = []
    cookie_net = {}
    net_error = False
    networks = None
    disks = None
    points = 5
    curent_time = time.strftime("%H:%M:%S")
    compute = Compute.objects.get(id=compute_id)

    try:
        conn = wvmInstance(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type,
                           vname)
        status = conn.get_status()
        cpu_usage = conn.cpu_usage()
        blk_usage = conn.disk_usage()
        net_usage = conn.net_usage()
        conn.close()
    except libvirtError:
        status = None
        blk_usage = None
        cpu_usage = None
        net_usage = None

    if status == 1:
        cookies = request.COOKIES
        if cookies.get('cpu') == '{}' or not cookies.get('cpu') or not cpu_usage:
            datasets['cpu'] = [0]
            datasets['timer'] = [curent_time]
        else:
            datasets['cpu'] = eval(cookies.get('cpu'))
            datasets['timer'] = eval(cookies.get('timer'))

        datasets['timer'].append(curent_time)
        datasets['cpu'].append(int(cpu_usage['cpu']))

        if len(datasets['timer']) > points:
            datasets['timer'].pop(0)
        if len(datasets['cpu']) > points:
            datasets['cpu'].pop(0)

        for blk in blk_usage:
            if cookies.get('hdd') == '{}' or not cookies.get('hdd') or not blk_usage:
                datasets_wr.append(0)
                datasets_rd.append(0)
            else:
                datasets['hdd'] = eval(cookies.get('hdd'))
                try:
                    datasets_rd = datasets['hdd'][blk['dev']][0]
                    datasets_wr = datasets['hdd'][blk['dev']][1]
                except:
                    blk_error = True

            if not blk_error:
                datasets_rd.append(int(blk['rd']) / 1048576)
                datasets_wr.append(int(blk['wr']) / 1048576)

                if len(datasets_rd) > points:
                    datasets_rd.pop(0)
                if len(datasets_wr) >= points + 1:
                    datasets_wr.pop(0)

            json_blk.append({'dev': blk['dev'], 'data': [datasets_rd, datasets_wr]})
            cookie_blk[blk['dev']] = [datasets_rd, datasets_wr]

        for net in net_usage:
            if cookies.get('net') == '{}' or not cookies.get('net') or not net_usage:
                datasets_rx.append(0)
                datasets_tx.append(0)
            else:
                datasets['net'] = eval(cookies.get('net'))
                try:
                    datasets_rx = datasets['net'][net['dev']][0]
                    datasets_tx = datasets['net'][net['dev']][1]
                except:
                    net_error = True

            if not net_error:
                datasets_rx.append(int(net['rx']) / 1048576)
                datasets_tx.append(int(net['tx']) / 1048576)

                if len(datasets_rx) > points:
                    datasets_rx.pop(0)
                if len(datasets_tx) > points:
                    datasets_tx.pop(0)

            json_net.append({'dev': net['dev'], 'data': [datasets_rx, datasets_tx]})
            cookie_net[net['dev']] = [datasets_rx, datasets_tx]

    data = json.dumps({'status': status, 'cpudata': datasets['cpu'], 'hdddata': json_blk, 'netdata': json_net, 'timeline':  datasets['timer']})

    response = HttpResponse()
    response['Content-Type'] = "text/javascript"
    if status == 1:
        response.cookies['cpu'] = datasets['cpu']
        response.cookies['timer'] = datasets['timer']
        response.cookies['hdd'] = cookie_blk
        response.cookies['net'] = cookie_net
    response.write(data)
    return response