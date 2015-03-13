from string import letters, digits
from random import choice
from bisect import insort
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.shortcuts import render
from django.utils.translation import ugettext_lazy as _
from computes.models import Compute
from instances.models import Instance
from users.models import UserInstance
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.connection import connection_manager
from libvirt import libvirtError, VIR_DOMAIN_XML_SECURE
from webvirtcloud.settings import QEMU_KEYMAPS, QEMU_CONSOLE_TYPES


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


def instance(request, compute_id, vname):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
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

    error_messages = []
    messages = []
    compute = Compute.objects.get(id=compute_id)
    computes = Compute.objects.all()
    computes_count = len(computes)
    keymaps = QEMU_KEYMAPS
    console_types = QEMU_CONSOLE_TYPES

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
    except libvirtError as lib_err:
        error_messages.append(lib_err)

    try:
        instance = Instance.objects.get(compute_id=compute_id, name=vname)
        if instance.uuid != uuid:
            instance.uuid = uuid
            instance.save()
    except Instance.DoesNotExist:
        instance = Instance(compute_id=compute_id, name=vname, uuid=uuid)
        instance.save()

    try:
        if request.method == 'POST':
            if 'poweron' in request.POST:
                conn.start()
                return HttpResponseRedirect(request.get_full_path() + '#poweron')
            if 'powercycle' in request.POST:
                conn.force_shutdown()
                conn.start()
                return HttpResponseRedirect(request.get_full_path() + '#powercycle')
            if 'poweroff' == request.POST.get('power', ''):
                conn.shutdown()
                return HttpResponseRedirect(request.get_full_path() + '#poweroff')
            if 'suspend' in request.POST:
                conn.suspend()
                return HttpResponseRedirect(request.get_full_path() + '#resume')
            if 'resume' in request.POST:
                conn.resume()
                return HttpResponseRedirect(request.get_full_path() + '#suspend')
            if 'delete' in request.POST:
                if conn.get_status() == 1:
                    conn.force_shutdown()
                try:
                    instance = Instance.objects.get(compute_id=compute_id, name=vname)
                    instance.delete()
                    if request.POST.get('delete_disk', ''):
                        conn.delete_disk()
                finally:
                    conn.delete()
                return HttpResponseRedirect(reverse('instances', args=[compute_id]))
            if 'snapshot' in request.POST:
                name = request.POST.get('name', '')
                conn.create_snapshot(name)
                return HttpResponseRedirect(request.get_full_path() + '#istaceshapshosts')
            if 'umount_iso' in request.POST:
                image = request.POST.get('path', '')
                dev = request.POST.get('umount_iso', '')
                conn.umount_iso(dev, image)
                return HttpResponseRedirect(request.get_full_path() + '#instancemedia')
            if 'mount_iso' in request.POST:
                image = request.POST.get('media', '')
                dev = request.POST.get('mount_iso', '')
                conn.mount_iso(dev, image)
                return HttpResponseRedirect(request.get_full_path() + '#instancemedia')
            if 'set_autostart' in request.POST:
                conn.set_autostart(1)
                return HttpResponseRedirect(request.get_full_path() + '#instancesettings')
            if 'unset_autostart' in request.POST:
                conn.set_autostart(0)
                return HttpResponseRedirect(request.get_full_path() + '#instancesettings')
            if 'resize' in request.POST:
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
                xml = request.POST.get('inst_xml', '')
                if xml:
                    conn._defineXML(xml)
                    return HttpResponseRedirect(request.get_full_path() + '#instancexml')
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
                        return HttpResponseRedirect(request.get_full_path() + '#console_pass')

            if 'set_console_keymap' in request.POST:
                keymap = request.POST.get('console_keymap', '')
                clear = request.POST.get('clear_keymap', False)
                if clear:
                    conn.set_console_keymap('')
                else:
                    conn.set_console_keymap(keymap)
                return HttpResponseRedirect(request.get_full_path() + '#console_keymap')

            if 'set_console_type' in request.POST:
                console_type = request.POST.get('console_type', '')
                conn.set_console_type(console_type)
                return HttpResponseRedirect(request.get_full_path() + '#console_type')

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
                return HttpResponseRedirect(reverse('instance', args=[compute_id, vname]))
            if 'delete_snapshot' in request.POST:
                snap_name = request.POST.get('name', '')
                conn.snapshot_delete(snap_name)
                return HttpResponseRedirect(request.get_full_path() + '#istaceshapshosts')
            if 'revert_snapshot' in request.POST:
                snap_name = request.POST.get('name', '')
                conn.snapshot_revert(snap_name)
                msg = _("Successful revert snapshot: ")
                msg += snap_name
                messages.append(msg)
            if 'clone' in request.POST:
                clone_data = {}
                clone_data['name'] = request.POST.get('name', '')

                for post in request.POST:
                    if 'disk' or 'meta' in post:
                        clone_data[post] = request.POST.get(post, '')

                conn.clone_instance(clone_data)
                return HttpResponseRedirect(reverse('instance', args=[compute_id, clone_data['name']]))

        conn.close()

    except libvirtError as err:
        error_messages.append(err)

    return render(request, 'instance.html', locals())