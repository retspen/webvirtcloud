import time
import json
import socket
import crypt
from string import letters, digits
from random import choice
from bisect import insort
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.shortcuts import render, get_object_or_404
from django.utils.translation import ugettext_lazy as _
from computes.models import Compute
from instances.models import Instance
from accounts.models import UserInstance, UserSSHKey
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
            if connection_manager.host_is_up(comp.type, comp.hostname):
                try:
                    conn = wvmHostDetails(comp, comp.login, comp.password, comp.type)
                    if conn.get_host_instances():
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


def instance(request, compute_id, vname):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    error_messages = []
    messages = []
    compute = get_object_or_404(Compute, pk=compute_id)
    computes = Compute.objects.all()
    computes_count = len(computes)
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)
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
                {'dev': disk['dev'], 'storage': disk['storage'],
                 'image': image, 'format': disk['format']})
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
        console_listen_locally = conn.get_console_listen_addr() in ["127.0.0.1", "::1"]

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

            if 'delete' in request.POST:
                if conn.get_status() == 1:
                    conn.force_shutdown()
                if request.POST.get('delete_disk', ''):
                    conn.delete_disk()
                conn.delete()

                instance = Instance.objects.get(compute_id=compute_id, name=vname)
                instance_name = instance.name
                instance.delete()

                if not request.user.is_superuser:
                    del_userinstance = UserInstance.objects.get(id=userinstace.id)
                    del_userinstance.delete()
                else:
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

            if 'resize' in request.POST:
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
                msg = _("Resize")
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

                if 'set_console_listen_addr' in request.POST:
                    console_listen_locally = request.POST.get("listen_locally", False) == "true"
                    if not conn.set_console_listen_addr('127.0.0.1' if console_listen_locally else '0.0.0.0'):
                        msg = _("Error setting console listen status. You should check that your instance have an graphic device.")
                        error_messages.append(msg)
                    else:
                        msg = _("Set VNC listen status")
                        addlogmsg(request.user.username, instance.name, msg)
                        return HttpResponseRedirect(request.get_full_path() + '#vncsettings')

                if 'set_console_passwd' in request.POST:
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

                if 'migrate' in request.POST:
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
                    msg = _("Migrate")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(reverse('instance', args=[compute_id, vname]))

                if 'clone' in request.POST:
                    clone_data = {}
                    clone_data['name'] = request.POST.get('name', '')

                    for post in request.POST:
                        if 'disk' or 'meta' in post:
                            clone_data[post] = request.POST.get(post, '')

                    conn.clone_instance(clone_data)
                    msg = _("Clone")
                    addlogmsg(request.user.username, instance.name, msg)
                    return HttpResponseRedirect(reverse('instance', args=[compute_id, clone_data['name']]))

        conn.close()

    except libvirtError as lib_err:
        error_messages.append(lib_err.message)
        addlogmsg(request.user.username, vname, lib_err.message)

    return render(request, 'instance.html', locals())


def inst_status(request, compute_id, vname):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('login'))

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


def inst_graph(request, compute_id, vname):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('login'))

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
