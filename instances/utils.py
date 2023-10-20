import os
import random
import string

from accounts.models import UserInstance, UserAttributes
from appsettings.settings import app_settings
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from vrtManager.connection import connection_manager
from vrtManager.instance import wvmInstance, wvmInstances

from .models import Instance


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
    ua, attributes_created = UserAttributes.objects.get_or_create(user=user)
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
                if disk["size"]:
                    disk_size += int(disk["size"]) >> 30

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
        existing_disk_devs = [disk["dev"] for disk in disks]

    # cd-rom bus could be virtio/sata, because of that we should check it also
    if media:
        existing_media_devs = [m["dev"] for m in media]

    for al in string.ascii_lowercase:
        dev = dev_base + al
        if dev not in existing_disk_devs and dev not in existing_media_devs:
            return dev
    raise Exception(_("None available device name"))


def get_network_tuple(network_source_str):
    network_source_pack = network_source_str.split(":", 1)
    if len(network_source_pack) > 1:
        return network_source_pack[1], network_source_pack[0]
    else:
        return network_source_pack[0], "net"


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
    finally:
        conn_migrate.close()

    try:
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
        conn_new.close()

    instance.compute = new_compute
    instance.save()


def refr(compute):
    if compute.status is True:
        domains = compute.proxy.wvm.listAllDomains()
        domain_names = [d.name() for d in domains]
        domain_uuids = [d.UUIDString() for d in domains]
        # Delete instances that're not on host
        Instance.objects.filter(compute=compute).exclude(name__in=domain_names).delete()
        Instance.objects.filter(compute=compute).exclude(uuid__in=domain_uuids).delete()
        # Create instances that're not in DB
        names = Instance.objects.filter(compute=compute).values_list("name", flat=True)
        for domain in domains:
            if domain.name() not in names:
                Instance(compute=compute, name=domain.name(), uuid=domain.UUIDString()).save()


def get_dhcp_mac_address(vname):
    dhcp_file = str(settings.BASE_DIR) + "/dhcpd.conf"
    mac = ""
    if os.path.isfile(dhcp_file):
        with open(dhcp_file, "r") as f:
            name_found = False
            for line in f:
                if "host %s." % vname in line:
                    name_found = True
                if name_found and "hardware ethernet" in line:
                    mac = line.split(" ")[-1].strip().strip(";")
                    break
    return mac


def get_random_mac_address():
    mac = settings.MAC_OUI + ":%02x:%02x:%02x" % (
        random.randint(0x00, 0xFF),
        random.randint(0x00, 0xFF),
        random.randint(0x00, 0xFF),
    )
    return mac


def get_clone_disk_name(disk, prefix, clone_name=""):
    if not disk["image"]:
        return None
    if disk["image"].startswith(prefix) and clone_name:
        suffix = disk["image"][len(prefix) :]
        image = f"{clone_name}{suffix}"
    elif "." in disk["image"] and len(disk["image"].rsplit(".", 1)[1]) <= 7:
        name, suffix = disk["image"].rsplit(".", 1)
        image = f"{name}-clone.{suffix}"
    else:
        image = f"{disk['image']}-clone"
    return image
