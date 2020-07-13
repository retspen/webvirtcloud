import os
import random
import string
from collections import OrderedDict

from django.conf import settings
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

from accounts.models import UserInstance
from appsettings.settings import app_settings
from logs.views import addlogmsg
from vrtManager.connection import connection_manager
from vrtManager.hostdetails import wvmHostDetails
from vrtManager.instance import wvmInstance, wvmInstances

from .models import Instance


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
    prefix = app_settings.CLONE_INSTANCE_DEFAULT_PREFIX
    free_names = []
    existing_names = [i.name for i in Instance.objects.filter(name__startswith=prefix)]
    index = 1
    while len(free_names) < size:
        new_name = prefix + str(index)
        if new_name not in existing_names:
            free_names.append(new_name)
        index += 1
    return free_names


def check_user_quota(user, instance, cpu, memory, disk_size):
    ua = user.userattributes
    msg = ""

    if user.is_superuser:
        return msg

    quota_debug = app_settings.QUOTA_DEBUG

    user_instances = UserInstance.objects.filter(user=user, instance__is_template=False)
    instance += user_instances.count()
    for usr_inst in user_instances:
        if connection_manager.host_is_up(
                usr_inst.instance.compute.type,
                usr_inst.instance.compute.hostname,
        ):
            conn = wvmInstance(
                usr_inst.instance.compute.hostname,
                usr_inst.instance.compute.login,
                usr_inst.instance.compute.password,
                usr_inst.instance.compute.type,
                usr_inst.instance.name,
            )
            cpu += int(conn.get_vcpu())
            memory += int(conn.get_memory())
            for disk in conn.get_disk_devices():
                if disk['size']:
                    disk_size += int(disk['size']) >> 30

    if ua.max_instances > 0 and instance > ua.max_instances:
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


def migrate_instance(
    new_compute,
    instance,
    user,
    live=False,
    unsafe=False,
    xml_del=False,
    offline=False,
    autoconverge=False,
    compress=False,
    postcopy=False,
):
    status = connection_manager.host_is_up(new_compute.type, new_compute.hostname)
    if not status:
        return
    if new_compute == instance.compute:
        return
    try:
        conn_migrate = wvmInstances(
            new_compute.hostname,
            new_compute.login,
            new_compute.password,
            new_compute.type,
        )

        autostart = instance.autostart
        conn_migrate.moveto(
            instance.proxy,
            instance.name,
            live,
            unsafe,
            xml_del,
            offline,
            autoconverge,
            compress,
            postcopy,
        )

        conn_new = wvmInstance(
            new_compute.hostname,
            new_compute.login,
            new_compute.password,
            new_compute.type,
            instance.name,
        )

        if autostart:
            conn_new.set_autostart(1)
    finally:
        conn_migrate.close()
        conn_new.close()

    instance.compute = new_compute
    instance.save()


def get_hosts_status(computes):
    """
        Function return all hosts all vds on host
        """
    compute_data = []
    for compute in computes:
        compute_data.append({
            'id': compute.id,
            'name': compute.name,
            'hostname': compute.hostname,
            'status': connection_manager.host_is_up(compute.type, compute.hostname),
            'type': compute.type,
            'login': compute.login,
            'password': compute.password,
            'details': compute.details,
        })
    return compute_data


def get_userinstances_info(instance):
    info = {}
    uis = UserInstance.objects.filter(instance=instance)
    info['count'] = uis.count()
    if info['count'] > 0:
        info['first_user'] = uis[0]
    else:
        info['first_user'] = None
    return info


def refr(compute):
    if compute.status is True:
        domains = compute.proxy.wvm.listAllDomains()
        domain_names = [d.name() for d in domains]
        # Delete instances that're not on host
        Instance.objects.filter(compute=compute).exclude(name__in=domain_names).delete()
        # Create instances that're not in DB
        names = Instance.objects.filter(compute=compute).values_list('name', flat=True)
        for domain in domains:
            if domain.name() not in names:
                Instance(compute=compute, name=domain.name(), uuid=domain.UUIDString()).save()


def refresh_instance_database(comp, inst_name, info, all_host_vms, user):
    # Multiple Instance Name Check
    instances = Instance.objects.filter(name=inst_name)
    if instances.count() > 1:
        for i in instances:
            user_instances_count = UserInstance.objects.filter(instance=i).count()
            if user_instances_count == 0:
                addlogmsg(user.username, i.name, _("Deleting due to multiple(Instance Name) records."))
                i.delete()

    # Multiple UUID Check
    instances = Instance.objects.filter(uuid=info['uuid'])
    if instances.count() > 1:
        for i in instances:
            if i.name != inst_name:
                addlogmsg(user.username, i.name, _("Deleting due to multiple(UUID) records."))
                i.delete()

    try:
        inst_on_db = Instance.objects.get(compute_id=comp["id"], name=inst_name)
        if inst_on_db.uuid != info['uuid']:
            inst_on_db.save()

        all_host_vms[comp["id"], comp["name"], comp["status"], comp["cpu"], comp["mem_size"],
                     comp["mem_perc"]][inst_name]['is_template'] = inst_on_db.is_template
        all_host_vms[comp["id"], comp["name"], comp["status"], comp["cpu"], comp["mem_size"],
                     comp["mem_perc"]][inst_name]['userinstances'] = get_userinstances_info(inst_on_db)
    except Instance.DoesNotExist:
        inst_on_db = Instance(compute_id=comp["id"], name=inst_name, uuid=info['uuid'])
        inst_on_db.save()


def get_user_instances(user):
    all_user_vms = {}
    user_instances = UserInstance.objects.filter(user=user)
    for usr_inst in user_instances:
        if connection_manager.host_is_up(usr_inst.instance.compute.type, usr_inst.instance.compute.hostname):
            conn = wvmHostDetails(
                usr_inst.instance.compute.hostname,
                usr_inst.instance.compute.login,
                usr_inst.instance.compute.password,
                usr_inst.instance.compute.type,
            )
            all_user_vms[usr_inst] = conn.get_user_instances(usr_inst.instance.name)
            all_user_vms[usr_inst].update({'compute_id': usr_inst.instance.compute.id})
    return all_user_vms


def get_host_instances(compute):
    all_host_vms = OrderedDict()

    # if compute.status:
    comp_node_info = compute.proxy.get_node_info()
    comp_mem = compute.proxy.get_memory_usage()
    comp_instances = compute.proxy.get_host_instances(True)

    # if comp_instances:
    comp_info = {
        "id": compute.id,
        "name": compute.name,
        "status": compute.status,
        "cpu": comp_node_info[3],
        "mem_size": comp_node_info[2],
        "mem_perc": comp_mem['percent'],
    }
    # refr(compute)
    all_host_vms[comp_info["id"], comp_info["name"], comp_info["status"], comp_info["cpu"], comp_info["mem_size"],
                 comp_info["mem_perc"]] = comp_instances
    for vm, info in comp_instances.items():
        # TODO: Delete this function completely
        refresh_instance_database(comp_info, vm, info, all_host_vms, User.objects.get(pk=1))

    # else:
    #     raise libvirtError(_(f"Problem occurred with host: {compute.name} - {status}"))
    return all_host_vms


def get_dhcp_mac_address(vname):
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


def get_random_mac_address():
    mac = '52:54:00:%02x:%02x:%02x' % (
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff),
    )
    return mac


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


# TODO: this function is not used
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
            'format': disk['format'],
        }
        clone_disks.append(new_disk)
    return clone_disks
