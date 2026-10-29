try:
    import crypt_r as crypt
except ImportError:
    import crypt
import difflib
import functools
import json
import os
import re
import socket
import subprocess
import time
from bisect import insort
from ipaddress import ip_address

from accounts.models import UserInstance, UserSSHKey
from admin.decorators import superuser_only
from appsettings.models import AppSettings
from appsettings.settings import app_settings
from computes.models import Compute
from computes.validators import validate_hostname, validate_login
from computes.utils import libvirt_compute_lock, libvirt_instance_lock, user_quota_lock
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import User
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.db.models import Prefetch, prefetch_related_objects
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_noop as _
from django.views.decorators.http import require_POST
from libvirt import (VIR_DOMAIN_PAUSED,
                     VIR_DOMAIN_RUNNING,
                     VIR_DOMAIN_SHUTOFF,
                     VIR_DOMAIN_UNDEFINE_KEEP_NVRAM,
                     VIR_DOMAIN_UNDEFINE_MANAGED_SAVE,
                     VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA,
                     VIR_DOMAIN_UNDEFINE_NVRAM,
                     VIR_ERR_NO_SUPPORT,
                     libvirtError)
from logs.audit import audit, audit_vm, changed_fields, failed_vm
from logs.audit import snapshot as audit_snapshot
from operations import claims, jobs
from operations.utils import busy_message, summary
from webvirtcloud.middleware import error_text, same_origin_referer
from vrtManager import util
from vrtManager.create import cpu_choices, wvmCreate
from vrtManager.instance import USAGE_MAX_WINDOW, wvmInstances
from vrtManager.interface import wvmInterface
from vrtManager.nodedevs import device_names, hostdev_problems, node_devices, pci_problems
from vrtManager.storage import wvmStorage
from vrtManager.util import randomPasswd

from instances.models import Instance

from . import addresses, report, utils
from .api.serializers import DestroyOptionsSerializer
from .forms import ConsoleForm, FlavorForm, NewVMForm
from .models import Flavor
from .states import STATES, UNKNOWN, state_label

# the VM page waits this long (seconds) for the compute's drbdadm status
DRBD_STATUS_TIMEOUT = 10
# the stats tab sends the sample of each answer back with its next poll
STATS_SAMPLE_SIGNER = signing.TimestampSigner(salt="instances.stats-sample")


def index(request):
    instances = None

    computes = list(Compute.objects.all().order_by("name"))
    for compute in computes:
        utils.refr(compute)
    # each host's VMs by name: the database keeps no order of its own
    prefetch_related_objects(computes, Prefetch("instance_set", queryset=Instance.objects.order_by("name")),
                             "instance_set__userinstance_set__user")

    show_hosts = request.user.is_superuser or request.user.has_perm("instances.view_instances")
    own_hosts_down = False
    if show_hosts:
        instances = Instance.objects.order_by("name").prefetch_related("userinstance_set__user")
    else:
        instances = Instance.objects.filter(
            userinstance__user=request.user
        ).order_by("name").prefetch_related("userinstance_set__user")
        # other users get no host names or connection errors, only whether
        # a host of their own VMs is down
        own = set(instances.values_list("compute_id", flat=True))
        own_hosts_down = any(c.status is not True for c in computes if c.pk in own)

    return render(
        request,
        "allinstances.html",
        {"computes": computes, "instances": instances, "show_hosts": show_hosts, "own_hosts_down": own_hosts_down,
         "reachable_computes": [c for c in computes if c.status is True],
         "unreachable_computes": [c for c in computes if c.status is not True],
         "states": [label for label, _color in STATES.values()] + [UNKNOWN[0]]},
    )


def _address_scope(user):
    """What the address search and the VM report read for the user: whether
    the user sees hosts, the registered VMs by (compute id, UUID), and the
    targets. Administrators read every compute, VMs the panel has not
    registered included; other users only their own VMs. A VM is its compute
    and UUID: one UUID may be defined on two hosts."""
    show_hosts = user.is_superuser or user.has_perm("instances.view_instances")
    if show_hosts:
        known = {(inst.compute_id, inst.uuid): inst for inst in Instance.objects.all()}
        return show_hosts, known, [addresses.Target(compute, None) for compute in Compute.objects.all()]
    known = {(inst.compute_id, inst.uuid): inst for inst in
             Instance.objects.filter(userinstance__user=user).select_related("compute")}
    scopes = {}
    for inst in known.values():
        scopes.setdefault(inst.compute_id, addresses.Target(inst.compute, set())).uuids.add(inst.uuid)
    return show_hosts, known, list(scopes.values())


def find_address(request):
    """
    The running VMs using an IP address or an address in a network, or the
    VMs with a NIC of a MAC address, shut-off ones too
    (instances/addresses.py), as JSON for the Instances page's dialog.
    Administrators search every compute, VMs the panel has not registered
    included, and see the hosts; other users only their own VMs, without
    hosts or host errors.
    """
    query = request.GET.get("q", "")
    mac = addresses.parse_mac(query)
    if mac is None:
        try:
            network = addresses.parse_query(query)
        except ValueError:
            return JsonResponse({"error": _("Enter an IP address, a network such as 192.0.2.0/24, or a MAC address.")},
                                status=400)
    show_hosts, known, targets = _address_scope(request.user)
    try:
        result = addresses.find_mac(targets, mac) if mac else addresses.find(targets, network)
    except addresses.Busy:
        return JsonResponse({"error": _("Too many searches are still running; try again shortly.")}, status=409)

    hosts = {target.compute.id: target.compute.name for target in targets}
    matches = []
    for match in result["matches"]:
        inst = known.get((match["compute_id"], match["uuid"]))
        if inst is None and not show_hosts:
            continue
        row = {key: match[key] for key in ("address", "mac", "sources", "conflict")}
        row.update(vm=inst.name if inst else match["name"], registered=inst is not None,
                   url=reverse("instances:instance", args=[inst.id]) + "#network" if inst else None)
        if show_hosts:
            row["host"] = hosts[match["compute_id"]]
        matches.append(row)
    coverage = {key: result[key] for key in ("checked", "no_agent", "unread")}
    if show_hosts:
        coverage.update(hosts_down=result["hosts_down"], hosts_unfinished=result["hosts_unfinished"])
    else:
        coverage["some_unchecked"] = bool(result["hosts_down"] or result["hosts_unfinished"])
    return JsonResponse({"matches": matches, "coverage": coverage, "read_at": timezone.now().isoformat()})


@superuser_only
def vm_report(request):
    """
    Every VM on every compute (shut-off ones and those the panel has not
    registered too), with its state, host, OS, size, addresses and owners,
    as an Excel workbook; a second sheet says what could not be read
    (instances/addresses.py inventory). Linked from the Administration menu.
    """
    known, targets = _address_scope(request.user)[1:]
    try:
        result = addresses.inventory(targets)
    except addresses.Busy:
        messages.error(request, _("Too many searches are still running; try again shortly."))
        return redirect("instances:index")

    hosts = {target.compute.id: target.compute.name for target in targets}
    owners = {}
    for owner in UserInstance.objects.select_related("user", "instance"):
        owners.setdefault((owner.instance.compute_id, owner.instance.uuid), []).append(owner.user.username)
    header = ["VM", "State", "Host", "OS", "OS family", "vCPUs", "Memory (MiB)", "IP addresses",
              "Address sources", "MAC addresses", "Owners", "In the panel"]
    rows = []
    for vm in result["vms"]:
        key = (vm["compute_id"], vm["uuid"])
        # a link-local address (fe80::) is not one to report: every NIC has its own
        reported = [(address, sources) for address, sources in vm["addresses"]
                    if not ip_address(address).is_link_local]
        found = {source for _address, sources in reported for source in sources}
        row = {"VM": vm["name"], "State": str(state_label(vm["state"])[0]), "Host": hosts[vm["compute_id"]],
               "OS": vm["os"], "OS family": vm["os_family"], "vCPUs": vm["vcpus"], "Memory (MiB)": vm["memory"],
               "IP addresses": ", ".join(address for address, _sources in reported),
               "Address sources": ", ".join(s for s in addresses.SOURCES.values() if s in found),
               "MAC addresses": ", ".join(vm["macs"]), "Owners": ", ".join(sorted(owners.get(key, []))),
               "In the panel": "yes" if key in known else "no"}
        rows.append(list(row.values()))

    notes = [f"Created: {timezone.localtime():%Y-%m-%d %H:%M}",
             f"VMs listed: {len(rows)}",
             f"Running VMs read: {result['checked']}",
             f"Without a connected guest agent (a static address on them cannot be seen): {result['no_agent']}",
             f"Guest agents not read (a paused VM, no answer in time, or an error): {result['unread']}"]
    if result["hosts_down"]:
        notes.append("Hosts not reached: " + ", ".join(result["hosts_down"]))
    if result["hosts_unfinished"]:
        notes.append("Hosts not finished in time: " + ", ".join(result["hosts_unfinished"]))
    response = HttpResponse(report.workbook("VMs", header, rows, "Coverage", notes),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="vms-{timezone.localtime():%Y%m%d-%H%M}.xlsx"'
    return response


def instance(request, pk):
    instance: Instance = get_instance(request.user, pk)
    compute: Compute = instance.compute
    # the page reads the VM from libvirt throughout; without the host it would
    # be the error page, with a connection error that names the host
    if compute.status is not True:
        if request.user.is_superuser or request.user.has_perm("instances.view_instances"):
            msg = _("The host %(host)s of '%(name)s' cannot be reached: %(error)s") % {
                "host": compute.name,
                "name": instance.name,
                "error": compute.connection_error,
            }
        else:
            msg = _("The host of '%(name)s' cannot be reached right now.") % {"name": instance.name}
        messages.error(request, msg + _(" Jobs on it can be followed under Jobs in the menu."))
        return redirect(reverse("instances:index"))
    # The page only reads the VM, and its getters read the same XML some 30
    # times: libvirt is asked once per kind of XML.
    with instance.proxy.cached_reads():
        return _instance_page(request, pk, instance, compute)


def _instance_page(request, pk, instance, compute):
    computes = Compute.objects.all().order_by("name")
    computes_count = computes.count()
    users = User.objects.all().order_by("username")
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)
    keymaps = settings.QEMU_KEYMAPS
    # The console form renders the VNC password, so only users who may manage
    # console settings get the form (and the password) at all.
    can_manage_console = utils.can_manage_console(request.user, instance)
    console_form = None
    if can_manage_console:
        console_form = ConsoleForm(instance=instance, can_set_listener=request.user.is_superuser)
    console_listener_addresses = settings.QEMU_CONSOLE_LISTENER_ADDRESSES
    bottom_bar = app_settings.VIEW_INSTANCE_DETAIL_BOTTOM_BAR
    try:
        userinstance = UserInstance.objects.get(
            instance__compute_id=compute.id,
            instance__name=instance.name,
            user__id=request.user.id,
        )
    except UserInstance.DoesNotExist:
        userinstance = None
    # The page offers only what the backend allows this user (get_instance
    # perm_type="change", utils.can_open_console); is_staff and the global
    # view_instances permission are read-only.
    can_open_console = utils.can_open_console(request.user, instance)
    can_power = request.user.is_superuser or userinstance is not None
    # get_instance(perm_type="delete"): a template only for superusers and staff owners
    can_delete = request.user.is_superuser or bool(
        userinstance and userinstance.is_delete and (request.user.is_staff or not instance.is_template)
    )
    # get_instance(perm_type="change"): a template only for superusers and staff owners
    can_change = request.user.is_superuser or bool(
        userinstance and userinstance.is_change and (request.user.is_staff or not instance.is_template)
    )
    can_clone = request.user.has_perm("instances.clone_instances") and (instance.is_template or can_change)
    can_snapshot = can_change and request.user.has_perm("instances.snapshot_instances")
    show_settings = (
        request.user.is_superuser or can_manage_console or can_clone or can_change or instance.guest_agent_ready
    )

    memory_range = [256, 512, 768, 1024, 2048, 3072, 4096, 6144, 8192, 16384]
    if instance.memory not in memory_range:
        insort(memory_range, instance.memory)
    if instance.cur_memory not in memory_range:
        insort(memory_range, instance.cur_memory)
    clone_free_names = utils.get_clone_free_names()

    default_bus = app_settings.INSTANCE_VOLUME_DEFAULT_BUS
    default_io = app_settings.INSTANCE_VOLUME_DEFAULT_IO
    default_discard = app_settings.INSTANCE_VOLUME_DEFAULT_DISCARD
    default_zeroes = app_settings.INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES
    default_cache = app_settings.INSTANCE_VOLUME_DEFAULT_CACHE
    default_format = app_settings.INSTANCE_VOLUME_DEFAULT_FORMAT
    # default_disk_owner_uid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
    # default_disk_owner_gid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)

    # clone_instance_auto_name = app_settings.CLONE_INSTANCE_AUTO_NAME

    # userinstances = UserInstance.objects.filter(instance=instance).order_by('user__username')
    userinstances = instance.userinstance_set.order_by("user__username")
    # Host resources
    vcpu_host = len(instance.vcpu_range)
    memory_host = instance.proxy.get_max_memory()
    bus_host = instance.proxy.get_disk_bus_types(instance.arch, instance.machine)
    networks_host = sorted(instance.proxy.get_networks())
    interfaces_host = sorted(instance.proxy.get_ifaces())
    nwfilters_host = instance.proxy.get_nwfilters()
    storages_host = sorted(instance.proxy.get_storages(True))
    net_models_host = instance.proxy.get_network_models()

    if app_settings.VM_DRBD_STATUS == "True":
        instance.drbd = drbd_status(request, pk)
        instance.save()

    usb_hostdevs, pci_hostdevs, other_hostdevs = instance.proxy.get_hostdevs()
    if usb_hostdevs or pci_hostdevs:
        names = device_names(instance.proxy)
        for row in usb_hostdevs:
            row["name"] = names.get((row["vendor"], row["product"]), "")
        for row in pci_hostdevs:
            row["name"] = names.get(row["address"], "")
    # owners see the devices their VM has; only superusers change them
    show_hostdevs = request.user.is_superuser or bool(usb_hostdevs or pci_hostdevs or other_hostdevs)
    show_settings = show_settings or show_hostdevs

    job_resource = claims.instance_key(instance.uuid)
    return render(request, "instance.html", locals(),)


def status(request, pk):
    instance = get_instance(request.user, pk)
    return JsonResponse({"status": instance.proxy.get_status()})


def _valid_ssh_target(compute):
    """The login and hostname reach ssh as a command-line argument; a compute
    whose values would inject an ssh option (an existing or bypassed row that
    the field validators did not cover) is skipped rather than run."""
    try:
        validate_login(compute.login)
        validate_hostname(compute.hostname)
    except ValidationError:
        return False
    return True


def drbd_status(request, pk):
    instance = get_instance(request.user, pk)
    result = "None DRBD"

    if instance.compute.type == 2 and _valid_ssh_target(instance.compute):
        conn = instance.compute.login + "@" + instance.compute.hostname
        try:
            remoteDrbdStatus = subprocess.run(
                ["ssh", "--", conn, "sudo", "/usr/sbin/drbdadm", "status"],
                stdout=subprocess.PIPE,
                text=True,
                timeout=DRBD_STATUS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return result

        # the VM's resources are its name or its name_SUFFIX, at the start of a line
        instanceFindDrbd = re.compile(
            "^" + re.escape(instance.name) + "(?:_[A-Z]+)? role:(.+?)\n  disk:(.+?)\n",
            re.IGNORECASE | re.MULTILINE,
        )
        instanceDrbd = instanceFindDrbd.findall(remoteDrbdStatus.stdout or "")
        if instanceDrbd:
            primaryCount = 0
            secondaryCount = 0
            statusDisk = "OK"

            for disk in instanceDrbd:
                if disk[0] == "Primary":
                    primaryCount = primaryCount + 1
                elif disk[0] == "Secondary":
                    secondaryCount = secondaryCount + 1
                if disk[1] != "UpToDate":
                    statusDisk = "NOK"

            if primaryCount > 0 and secondaryCount > 0:
                statusRole = "NOK"
            else:
                if primaryCount > secondaryCount:
                    statusRole = "Primary"
                else:
                    statusRole = "Secondary"

            result = statusRole + "/" + statusDisk

    return result


def _stats_sample(instance, token):
    """The usage sample in a token of this VM's stats on its current compute,
    or None when there is none, it is altered or too old."""
    if not token:
        return None
    try:
        data = STATS_SAMPLE_SIGNER.unsign_object(token, max_age=USAGE_MAX_WINDOW)
    except signing.BadSignature:
        return None
    if data.get("vm") != [instance.id, instance.compute_id, instance.uuid]:
        return None
    return data["sample"]


def stats(request, pk):
    instance = get_instance(request.user, pk)
    usage = instance.proxy.usage(_stats_sample(instance, request.GET.get("sample")))
    mem_usage = instance.proxy.mem_usage()

    def mega(value):
        return None if value is None else value / 10**6

    result = {
        "cpudata": None if usage["cpu"] is None else round(usage["cpu"], 1),
        "memdata": mem_usage,
        # MB/s and Mbit/s
        "blkdata": [{"dev": disk["dev"], "data": [mega(disk["rd"]), mega(disk["wr"])]} for disk in usage["disks"]],
        "netdata": [{"dev": nic["dev"], "data": [mega(nic["rx"]), mega(nic["tx"])]} for nic in usage["nics"]],
        "timeline": time.strftime("%H:%M:%S"),
    }
    if "sample" in usage:
        result["window"] = None if usage["window"] is None else round(usage["window"], 1)
        result["sample"] = STATS_SAMPLE_SIGNER.sign_object(
            {"vm": [instance.id, instance.compute_id, instance.uuid], "sample": usage["sample"]}, compress=True
        )
    return JsonResponse(result)


def osinfo(request, pk):
    instance = get_instance(request.user, pk)
    try:
        return JsonResponse(instance.proxy.osinfo())
    except libvirtError as err:
        return JsonResponse({"error": error_text(request, err)}, status=400)


@superuser_only
def guess_mac_address(request, vname):
    data = {"vname": vname}
    mac = utils.get_dhcp_mac_address(vname)
    if not mac:
        mac = utils.get_random_mac_address()
    data["mac"] = mac
    return JsonResponse(data)


@superuser_only
def random_mac_address(request):
    data = dict()
    data["mac"] = utils.get_random_mac_address()
    return JsonResponse(data)


@superuser_only
def guess_clone_name(request):
    dhcp_file = utils.dhcpd_conf()
    prefix = app_settings.CLONE_INSTANCE_DEFAULT_PREFIX
    if os.path.isfile(dhcp_file):
        instance_names = [
            i.name for i in Instance.objects.filter(name__startswith=prefix)
        ]
        with open(dhcp_file, "r") as f:
            for line in f:
                line = line.strip()
                if f"host {prefix}" in line:
                    fqdn = line.split(" ")[1]
                    hostname = fqdn.split(".")[0]
                    if hostname.startswith(prefix) and hostname not in instance_names:
                        return JsonResponse({"name": hostname})
    return JsonResponse({})


def sshkeys(request, pk):
    """
    :param request:
    :param vname:
    :return:
    """
    instance = get_instance(request.user, pk)
    instance_keys = []
    userinstances = UserInstance.objects.filter(instance=instance)

    for ui in userinstances:
        keys = UserSSHKey.objects.filter(user=ui.user)
        for k in keys:
            instance_keys.append(k.keypublic)
    if request.GET.get("plain", ""):
        response = "\n".join(instance_keys)
        response += "\n"
        return HttpResponse(response, content_type="text/plain; charset=utf-8")
    return JsonResponse(instance_keys, safe=False)


def get_safe_redirect(request, default=None):
    return redirect(same_origin_referer(request, default or reverse("instances:index")))


def _is_int(value):
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def _back(request, pk, tab):
    """Back to the page the form was on, at the given tab; the VM page if
    the Referer is missing or from another site."""
    return redirect(same_origin_referer(request, reverse("instances:instance", args=[pk])) + "#" + tab)


def get_instance(user, pk, perm_type="view"):
    """
    Check that instance is available for user, if not raise 404 or PermissionDenied.
    perm_type:
      - 'view': superuser, has_perm("instances.view_instances"), or UserInstance owner
      - 'power': superuser or UserInstance owner
      - 'change': superuser or (UserInstance owner and is_change)
      - 'delete': superuser or (UserInstance owner and is_delete)
      A template is changed or deleted only by superusers and staff owners.
    """
    valid_perms = {"view", "power", "change", "delete"}
    if perm_type not in valid_perms:
        raise PermissionDenied

    instance = get_object_or_404(Instance, pk=pk)
    user_instances = user.userinstance_set.filter(instance=instance)
    has_owner_rel = user_instances.exists()

    if not (
        user.is_superuser
        or user.has_perm("instances.view_instances")
        or has_owner_rel
    ):
        raise Http404()

    if user.is_superuser or perm_type == "view":
        return instance

    user_inst = user_instances.first()
    if perm_type == "power":
        if not has_owner_rel:
            raise PermissionDenied
    elif perm_type == "change":
        # A template is changed only by superusers (above) and staff owners
        if not (user_inst and user_inst.is_change) or (instance.is_template and not user.is_staff):
            raise PermissionDenied
    elif perm_type == "delete":
        if not (user_inst and user_inst.is_delete) or (instance.is_template and not user.is_staff):
            raise PermissionDenied
    else:
        raise PermissionDenied

    return instance


def _power_instance(user, pk):
    """The VM to power on, off or cycle: a VM an administrator paused stays
    paused until an administrator resumes it."""
    instance = get_instance(user, pk, perm_type="power")
    if not user.is_superuser and instance.proxy.get_status() == VIR_DOMAIN_PAUSED:
        raise PermissionDenied
    return instance


def from_script(request):
    """A form a page's script sends and answers itself: the create page's
    flavor forms (it swaps in the reply), the XML editor's dialog (JSON)."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _busy(request, pk, busy):
    if hasattr(request, "accepted_renderer") or from_script(request):
        blocker = busy.blocker
        return JsonResponse({"detail": busy_message(busy, request.user),
                             "operation": summary(blocker, request.user) if blocker else None}, status=409)
    messages.error(request, busy_message(busy, request.user))
    return get_safe_redirect(request, default=reverse("instances:instance", args=[pk]))


def _moved(request, pk):
    if hasattr(request, "accepted_renderer") or from_script(request):
        return JsonResponse({"detail": "The VM was moved meanwhile; try again."}, status=409)
    messages.error(request, _("The VM was moved meanwhile; try again."))
    return get_safe_redirect(request, default=reverse("instances:instance", args=[pk]))


def _moved_meanwhile(pk, inst):
    """A migration may have moved the VM before the request took its
    compute's claim: the claim held is then the old compute's. The retry locks
    the new one (or finds the record merged away)."""
    return not Instance.objects.filter(pk=pk, compute_id=inst.compute_id).exists()


def serialize_instance_mutation(func):
    """Serialize one VM, after checking visibility, without blocking sibling VMs."""
    @functools.wraps(func)
    def wrapper(request, pk, *args, **kwargs):
        inst = get_instance(request.user, pk)
        try:
            with libvirt_instance_lock(inst):
                if _moved_meanwhile(pk, inst):
                    return _moved(request, pk)
                return func(request, pk, *args, **kwargs)
        except claims.Busy as busy:
            return _busy(request, pk, busy)

    return wrapper


def quota_refused(quota_msg, refused):
    """The message for a refused change: refused is the action's own
    'User %(quota_msg)s quota reached, ...' text, already formatted."""
    if quota_msg == utils.QUOTA_UNVERIFIED:
        return _("The quota cannot be checked because a host of your virtual machines cannot be reached. Nothing was changed.")
    return refused


def serialize_user_quota(func):
    """Outermost lock for quota-checked changes: concurrent requests of one
    user (also on different computes) must not pass the check together."""
    @functools.wraps(func)
    def wrapper(request, pk, *args, **kwargs):
        if request.user.is_superuser:  # quotas do not apply
            return func(request, pk, *args, **kwargs)
        try:
            with user_quota_lock(request.user):
                return func(request, pk, *args, **kwargs)
        except claims.Busy as busy:
            return _busy(request, pk, busy)

    return wrapper


def serialize_compute_mutation(func):
    """Hold the whole compute: disk deletions must not race another VM attaching that disk."""
    @functools.wraps(func)
    def wrapper(request, pk, *args, **kwargs):
        inst = get_instance(request.user, pk)
        if request.method in ("GET", "HEAD"):  # e.g. the destroy confirmation page
            return func(request, pk, *args, **kwargs)
        try:
            with libvirt_compute_lock(inst.compute):
                if _moved_meanwhile(pk, inst):
                    return _moved(request, pk)
                return func(request, pk, *args, **kwargs)
        except claims.Busy as busy:
            return _busy(request, pk, busy)

    return wrapper


DISK_FORMAT_RE = re.compile(r"^[a-z0-9]+$")
DISK_SERIAL_RE = re.compile(r"^[A-Za-z0-9_.+-]*$")
VOLUME_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")


def invalid_disk_options(
    instance,
    bus=None,
    cache=None,
    io=None,
    discard=None,
    zeroes=None,
    format=None,
    serial=None,
):
    """
    Return the names of the given disk options whose values are not allowed.
    These values end up in libvirt disk XML, so they must come from the
    hypervisor's own lists (or match a strict pattern). None means "not given".
    """
    proxy = instance.proxy
    checks = {
        "bus": (
            bus,
            lambda v: v in proxy.get_disk_bus_types(instance.arch, instance.machine),
        ),
        "cache": (cache, lambda v: v in proxy.get_cache_modes()),
        "io": (io, lambda v: v in proxy.get_io_modes()),
        "discard": (discard, lambda v: v in proxy.get_discard_modes()),
        "detect_zeroes": (zeroes, lambda v: v in proxy.get_detect_zeroes_modes()),
        "format": (format, lambda v: bool(DISK_FORMAT_RE.fullmatch(v))),
        "serial": (serial, lambda v: bool(DISK_SERIAL_RE.fullmatch(v))),
    }
    return [
        name
        for name, (value, is_valid) in checks.items()
        if value is not None and not is_valid(value)
    ]


def reject_disk_options(request, pk, invalid):
    messages.error(
        request,
        _("Invalid disk options: %(options)s") % {"options": ", ".join(invalid)},
    )
    return _back(request, pk, "disks")


@require_POST
@serialize_instance_mutation
def poweron(request, pk):
    instance = _power_instance(request.user, pk)
    if instance.is_template:
        messages.warning(request, _("Templates cannot be started."))
    else:
        with audit_vm(request, instance, "power on"):
            instance.proxy.start()

    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id])
    )


@require_POST
@serialize_instance_mutation
def powercycle(request, pk):
    instance = _power_instance(request.user, pk)
    if instance.is_template:
        messages.warning(request, _("Templates cannot be started."))
    else:
        with audit_vm(request, instance, "power cycle"):
            instance.proxy.force_shutdown()
            instance.proxy.start()
    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id])
    )


@require_POST
@serialize_instance_mutation
def poweroff(request, pk):
    instance = _power_instance(request.user, pk)
    with audit_vm(request, instance, "power off"):
        instance.proxy.shutdown()

    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id])
    )


@require_POST
@superuser_only
@serialize_instance_mutation
def suspend(request, pk):
    instance = get_instance(request.user, pk)
    with audit_vm(request, instance, "suspend"):
        instance.proxy.suspend()
    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id])
    )


@require_POST
@superuser_only
@serialize_instance_mutation
def resume(request, pk):
    instance = get_instance(request.user, pk)
    with audit_vm(request, instance, "resume"):
        instance.proxy.resume()
    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id])
    )


@require_POST
@serialize_instance_mutation
def force_off(request, pk):
    instance = _power_instance(request.user, pk)
    with audit_vm(request, instance, "force off"):
        instance.proxy.force_shutdown()
    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id])
    )


@serialize_compute_mutation
def destroy(request, pk):
    if request.method in ["POST", "DELETE"]:
        instance = get_instance(request.user, pk, perm_type="delete")
        # an API request is a DRF request whose body is in .data; refused
        # options stop nothing
        options = DestroyOptionsSerializer(data=getattr(request, "data", request.POST))
        options.is_valid(raise_exception=True)
        with libvirt_instance_lock(instance):
            with audit_vm(request, instance, "delete"):
                proxy = instance.proxy
                # Paused and other active states must stop too, or the VM keeps
                # running as a transient domain after the undefine.
                if proxy.instance.isActive():
                    proxy.force_shutdown()

                to_delete, shared = [], []
                if options.validated_data["delete_disk"]:
                    to_delete, shared = proxy.split_disk_paths_by_use()

                # Undefine before deleting any disk: if it fails, nothing is lost.
                # Snapshot metadata goes with the domain; internal snapshot data
                # stays in the disk images that are kept.
                flags = VIR_DOMAIN_UNDEFINE_MANAGED_SAVE | VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
                if options.validated_data["delete_nvram"]:
                    flags |= VIR_DOMAIN_UNDEFINE_NVRAM
                else:
                    flags |= VIR_DOMAIN_UNDEFINE_KEEP_NVRAM
                proxy.delete(flags)
                instance.delete()

            # each disk has its own row: the VM is gone even if one is kept
            for path in to_delete:
                try:
                    with audit_vm(request, instance, f"delete volume {path}"):
                        proxy.get_volume_by_path(path).delete(0)
                except libvirtError as err:
                    messages.error(request, _("Disk %(path)s was not deleted: %(err)s") % {"path": path, "err": error_text(request, err)})
            for path in shared:
                messages.warning(request, _("Disk %(path)s is used by another VM and was kept") % {"path": path})
        return redirect(reverse("instances:index"))

    instance = get_instance(request.user, pk, perm_type="delete")
    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except UserInstance.DoesNotExist:
        userinstance = UserInstance(
            is_delete=request.user.is_superuser
        )

    return render(
        request,
        "instances/destroy_instance_form.html",
        {
            "instance": instance,
            "userinstance": userinstance,
            # get_instance(perm_type="delete") above already refused the rest
            "can_delete": True,
        },
    )


@require_POST
@superuser_only
def migrate(request, pk):
    get_instance(request.user, pk)
    compute_id = request.POST.get("compute_id", "")
    if not compute_id.isdigit():
        raise Http404
    target_host = get_object_or_404(Compute, pk=compute_id)
    raw = {"instance": pk, "target": target_host.pk, "live": request.POST.get("live_migrate"),
           "unsafe": request.POST.get("unsafe_migrate"), "offline": request.POST.get("offline_migrate"),
           "autoconverge": request.POST.get("autoconverge"), "compress": request.POST.get("compress"),
           "delete_source": request.POST.get("delete_source"),
           "disk_pools": {key.removeprefix("pool-"): value for key, value in request.POST.items()
                          if key.startswith("pool-")}}
    try:
        op = jobs.submit("instance.migrate", request.user, raw, request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        return _busy(request, pk, busy)
    except (jobs.SubmissionConflict, libvirtError) as err:
        messages.error(request, error_text(request, err))
    else:
        jobs.remember_job(request, op)
    return get_safe_redirect(request, default=reverse("instances:instance", args=[pk]))


@require_POST
@superuser_only
def move_disk(request, pk):
    get_instance(request.user, pk)
    raw = {"instance": pk, "dev": request.POST.get("dev", ""), "pool": request.POST.get("pool", "")}
    try:
        op = jobs.submit("disk.move", request.user, raw, request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        return _busy(request, pk, busy)
    except (jobs.SubmissionConflict, libvirtError) as err:
        messages.error(request, error_text(request, err))
    else:
        jobs.remember_job(request, op)
    return _back(request, pk, "disks")


@superuser_only
def migrate_plan(request, pk):
    """The disks of the Migrate tab for the chosen destination, loaded when
    one is chosen: each with the pools of the destination it can be copied
    into, or the storage both hosts share."""
    instance = get_instance(request.user, pk)
    compute_id = request.GET.get("compute_id", "")
    if not compute_id.isdigit():
        raise Http404
    target = get_object_or_404(Compute, pk=compute_id)
    dest = None
    try:
        dest = wvmInstances(target.hostname, target.login, target.password, target.type)
        pools = [{"name": name, "directory": directory, "free": pool.info()[3]}
                 for name, (pool, directory) in sorted(dest.file_pools().items())]
        disks = dest.disk_plan(instance.proxy, instance.proxy.instance.XMLDesc(0))
        for disk in disks:
            # a copy goes by default to the pool on the same directory, else the first
            names = [pool["name"] for pool in pools if pool["directory"] == os.path.dirname(disk["path"])]
            names = names or [pool["name"] for pool in pools]
            disk["default"] = names[0] if names else None
        context = {"disks": disks, "pools": pools, "shut_off": instance.proxy.get_status() == 5}
    except libvirtError as err:
        context = {"error": error_text(request, err)}
    finally:
        if dest is not None:
            dest.close()
    return render(request, "instances/migrate_plan.html", context)


GSTFSD_PORT = 16510
GSTFSD_TIMEOUT = 120  # gstfsd answers within its 100 s limit for a request (GSTFSD_DEADLINE)


def gstfsd_request(hostname, data):
    """Send one request to gstfsd and return its JSON reply; an error reply or
    a failed exchange raises OperationError with the reason."""
    try:
        # the host name may resolve to IPv4 or IPv6
        s = socket.create_connection((hostname, GSTFSD_PORT), timeout=GSTFSD_TIMEOUT)
    except OSError as err:
        raise util.OperationError(_("gstfsd error: %(err)s") % {"err": err}) from err
    try:
        s.sendall(json.dumps(data).encode())
        # gstfsd sends one reply and closes the connection
        reply = json.loads(b"".join(iter(lambda: s.recv(4096), b"")))
    except (OSError, ValueError) as err:
        raise util.OperationError(_("gstfsd error: %(err)s") % {"err": err}) from err
    finally:
        s.close()
    if reply["return"] != "success":
        raise util.OperationError(reply["message"])
    return reply


# root password and SSH key: gstfsd changes a shut-off VM's disk, the QEMU
# guest agent a running VM
AGENT_OR_SHUT_OFF = _("Shut the VM down, or start its QEMU guest agent, and try again")


# libvirt's value; bindings built against older libvirt (Ubuntu 24.04's) lack
# the name, and the code comes from the host's libvirtd
VIR_ERR_AGENT_COMMAND_TIMEOUT = 112


def access_error(request, err):
    """The error of a root password or SSH key change. A command that timed
    out was sent to the agent, which still runs it when it answers again."""
    text = error_text(request, err)
    if isinstance(err, libvirtError) and err.get_error_code() == VIR_ERR_AGENT_COMMAND_TIMEOUT:
        text += " " + _("The change may still be made when the agent answers again.")
    return text


@require_POST
@serialize_instance_mutation
def set_root_pass(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")

    if request.method == "POST":
        passwd = request.POST.get("passwd", None)
        if passwd:
            passwd_hash = crypt.crypt(passwd, crypt.mksalt(crypt.METHOD_SHA512))
            # gstfsd opens the domain by name: send the host's current one.
            data = {"action": "password", "passwd": passwd_hash, "vname": instance.proxy.instance.name()}

            status = instance.proxy.get_status()
            if status == 5 or (status == 1 and instance.guest_agent_ready):
                try:
                    with audit_vm(request, instance, "reset root password"):
                        if status == 5:
                            gstfsd_request(instance.compute.hostname, data)
                        else:
                            instance.proxy.set_user_password("root", passwd_hash)
                except (util.OperationError, libvirtError) as err:
                    messages.error(request, access_error(request, err))
                else:
                    messages.success(request, _("Reset root password"))
            else:
                messages.error(request, AGENT_OR_SHUT_OFF)
        else:
            messages.error(request, _("Enter a password"))
    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id]) + "#access"
    )


@require_POST
@serialize_instance_mutation
def add_public_key(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")

    if request.method == "POST":
        sshkeyid = request.POST.get("sshkeyid", "")
        if not _is_int(sshkeyid):
            messages.error(request, _("Select an SSH public key"))
            return get_safe_redirect(
                request, default=reverse("instances:instance", args=[instance.id]) + "#access"
            )
        publickey = get_object_or_404(UserSSHKey, id=sshkeyid, user=request.user)
        data = {
            "action": "publickey",
            "key": publickey.keypublic,
            "vname": instance.proxy.instance.name(),
        }

        status = instance.proxy.get_status()
        if status == 5 or (status == 1 and instance.guest_agent_ready):
            try:
                with audit_vm(request, instance, f"install SSH key {publickey.keyname}"):
                    if status == 5:
                        gstfsd_request(instance.compute.hostname, data)
                    else:
                        instance.proxy.add_authorized_key("root", publickey.keypublic)
            except (util.OperationError, libvirtError) as err:
                messages.error(request, access_error(request, err))
            else:
                messages.success(request, _("Installed new SSH public key %(keyname)s") % {
                    "keyname": publickey.keyname
                })
        else:
            messages.error(request, AGENT_OR_SHUT_OFF)
    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id]) + "#access"
    )


@require_POST
@serialize_user_quota
@serialize_instance_mutation
def resizevm_cpu(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    vcpu = instance.proxy.get_vcpu()

    new_vcpu = request.POST.get("vcpu", "")
    new_cur_vcpu = request.POST.get("cur_vcpu", "")
    if not _is_int(new_vcpu) or not _is_int(new_cur_vcpu):
        messages.error(request, _("Enter a whole number of vCPUs"))
        return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")
    # a running VM would get them only at its next start, past the quota counted now
    if instance.proxy.instance.isActive():
        messages.error(request, _("Shut off the VM to change its vCPUs"))
        return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")
    if int(new_cur_vcpu) > int(new_vcpu):
        messages.error(request, _("The current vCPUs cannot be more than the maximum"))
        return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")

    quota_msg = utils.check_user_quota(
        request.user, 0, int(new_vcpu) - vcpu, 0, 0
    )
    if not request.user.is_superuser and quota_msg:
        msg = quota_refused(quota_msg, _(
            "User %(quota_msg)s quota reached, cannot resize CPU of '%(instance_name)s'!"
        ) % {
            "quota_msg": quota_msg,
            "instance_name": instance.name,
        })
        messages.error(request, msg)
    else:
        cur_vcpu = new_cur_vcpu
        vcpu = new_vcpu
        with audit_vm(request, instance, f"set vCPUs to {cur_vcpu} (maximum {vcpu})"):
            instance.proxy.resize_cpu(cur_vcpu, vcpu)
        msg = _("CPU is resized:  %(old)s to %(new)s") % {
            "old": cur_vcpu,
            "new": vcpu,
        }
        messages.success(request, msg)
    return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")


@require_POST
@serialize_user_quota
@serialize_instance_mutation
def resize_memory(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    memory = instance.proxy.get_memory()
    cur_memory = instance.proxy.get_cur_memory()

    new_memory = request.POST.get("memory", "")
    new_memory_custom = request.POST.get("memory_custom", "")
    if new_memory_custom:
        new_memory = new_memory_custom
    new_cur_memory = request.POST.get("cur_memory", "")
    new_cur_memory_custom = request.POST.get("cur_memory_custom", "")
    if new_cur_memory_custom:
        new_cur_memory = new_cur_memory_custom
    # The quota charges the maximum. An active VM keeps it (resize_mem changes
    # only the current memory there); pass the current maximum, so a VM that
    # shuts down meanwhile does not get an unchecked one.
    if instance.proxy.instance.isActive():
        new_memory = memory
    if not _is_int(new_memory) or not _is_int(new_cur_memory):
        messages.error(request, _("Enter a whole number for memory"))
        return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")
    if int(new_cur_memory) > int(new_memory):
        messages.error(request, _("The current memory cannot be more than the maximum"))
        return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")
    quota_msg = utils.check_user_quota(request.user, 0, 0, int(new_memory) - memory, 0)
    if not request.user.is_superuser and quota_msg:
        msg = quota_refused(quota_msg, _(
            "User %(quota_msg)s quota reached, cannot resize memory of '%(instance_name)s'!"
        ) % {
            "quota_msg": quota_msg,
            "instance_name": instance.name,
        })
        messages.error(request, msg)
    else:
        with audit_vm(request, instance, f"set memory to {new_cur_memory} MiB (maximum {new_memory} MiB)"):
            instance.proxy.resize_mem(new_cur_memory, new_memory)
        msg = _(
            "Memory is resized: current/max: %(old_cur)s/%(old_max)s to %(new_cur)s/%(new_max)s"
        ) % {
            "old_cur": cur_memory,
            "old_max": memory,
            "new_cur": new_cur_memory,
            "new_max": new_memory,
        }
        messages.success(request, msg)

    return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")


@require_POST
@serialize_user_quota
@serialize_instance_mutation
def resize_disk(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    disks = instance.proxy.get_disk_devices()

    disks_new = list()
    for disk in disks:
        # an empty field leaves the disk as it is; a disk outside a pool has no size and no field
        size = request.POST.get("disk_size_" + disk["dev"], "")
        if not size or disk["size"] is None:
            continue
        if not _is_int(size):
            messages.error(request, _("Enter disk sizes as whole GiB"))
            return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")
        if int(size) << 30 > disk["size"]:
            disk["size_new"] = int(size) << 30
            disks_new.append(disk)

    if not disks_new:
        messages.warning(request, _("No disks were selected or valid for resizing."))
        return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")

    disk_sum = sum([disk["size"] >> 30 for disk in disks_new])
    disk_new_sum = sum([disk["size_new"] >> 30 for disk in disks_new])
    quota_msg = utils.check_user_quota(
        request.user, 0, 0, 0, disk_new_sum - disk_sum
    )
    if not request.user.is_superuser and quota_msg:
        msg = quota_refused(quota_msg, _(
            "User %(quota_msg)s quota reached, cannot resize disks of '%(instance_name)s'!"
        ) % {
            "quota_msg": quota_msg,
            "instance_name": instance.name,
        })
        messages.error(request, msg)
    else:
        for disk in disks_new:
            try:
                with audit_vm(request, instance, f"resize disk {disk['dev']} to {disk['size_new'] >> 30} GiB"):
                    instance.proxy.resize_disk([disk])
            except libvirtError as err:
                # an LVM pool, for one, cannot resize its volumes
                if err.get_error_code() != VIR_ERR_NO_SUPPORT:
                    raise
                messages.error(request, _("The storage pool of %(dev)s cannot resize its volumes") % {"dev": disk["dev"]})
                continue
            messages.success(request, _("Disk is resized: %(dev)s") % {"dev": disk["dev"]})

    return redirect(reverse("instances:instance", args=[instance.id]) + "#resize")


@require_POST
@superuser_only
@serialize_instance_mutation
def add_new_vol(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    storage = request.POST.get("storage", "")
    name = request.POST.get("name", "")
    format = request.POST.get("format", app_settings.INSTANCE_VOLUME_DEFAULT_FORMAT)
    size = request.POST.get("size", 0)
    meta_prealloc = True if request.POST.get("meta_prealloc", False) else False
    bus = request.POST.get("bus", app_settings.INSTANCE_VOLUME_DEFAULT_BUS)
    cache = request.POST.get("cache", app_settings.INSTANCE_VOLUME_DEFAULT_CACHE)

    invalid = invalid_disk_options(instance, bus=bus, cache=cache, format=format)
    if not VOLUME_NAME_RE.fullmatch(name):
        invalid.append("name")
    if invalid:
        return reject_disk_options(request, pk, invalid)

    with audit_vm(request, instance, f"attach new disk {storage}/{name}"):
        conn_create = wvmCreate(
            instance.compute.hostname,
            instance.compute.login,
            instance.compute.password,
            instance.compute.type,
        )
        # a name either definition uses is taken: on an active VM a disk can be
        # pending in the persistent one only
        target_dev = utils.get_new_disk_dev(
            instance.media + instance.config_media, instance.disks + instance.config_disks, bus
        )

        source = conn_create.create_volume(
            storage,
            name,
            size,
            format,
            meta_prealloc,
            int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID),
            int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID),
        )

        conn_pool = wvmStorage(
            instance.compute.hostname,
            instance.compute.login,
            instance.compute.password,
            instance.compute.type,
            storage,
        )

        pool_type = conn_pool.get_type()
        disk_type = conn_pool.get_volume_type(os.path.basename(source))
        # the pool decides: only a dir pool keeps the asked format, the others create raw
        format = util.vol_driver_type(conn_pool.get_volume_format_type(os.path.basename(source)), pool_type)

        if pool_type == "rbd":
            source_info = conn_pool.get_rbd_source()
        else:  # add more disk types to handle different pool and disk types
            source_info = None

        instance.proxy.attach_disk(
            target_dev,
            source,
            source_info=source_info,
            pool_type=pool_type,
            disk_type=disk_type,
            target_bus=bus,
            format_type=format,
            cache_mode=cache,
        )
    return _back(request, pk, "disks")


@require_POST
@superuser_only
@serialize_instance_mutation
def add_existing_vol(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    storage = request.POST.get("selected_storage", "")
    name = request.POST.get("vols", "")
    bus = request.POST.get("bus", app_settings.INSTANCE_VOLUME_DEFAULT_BUS)
    cache = request.POST.get("cache", app_settings.INSTANCE_VOLUME_DEFAULT_CACHE)

    invalid = invalid_disk_options(instance, bus=bus, cache=cache)
    if invalid:
        return reject_disk_options(request, pk, invalid)

    conn_create = wvmStorage(
        instance.compute.hostname,
        instance.compute.login,
        instance.compute.password,
        instance.compute.type,
        storage,
    )

    # Only volumes that really exist in the selected pool; this also rules
    # out path traversal through the volume name.
    if name not in conn_create.get_volumes():
        return reject_disk_options(request, pk, ["vols"])

    pool_type = conn_create.get_type()
    format_type = util.vol_driver_type(conn_create.get_volume_format_type(name), pool_type)
    disk_type = conn_create.get_volume_type(name)
    if pool_type == "rbd":
        source_info = conn_create.get_rbd_source()
        path = conn_create.get_source_name()
        source = f"{path}/{name}"
    else:
        source_info = None
        # an iSCSI volume's path is not the pool target plus its name
        source = conn_create.get_volume(name).path()

    target_dev = utils.get_new_disk_dev(
        instance.media + instance.config_media, instance.disks + instance.config_disks, bus
    )

    with audit_vm(request, instance, f"attach disk {storage}/{name} as {target_dev}"):
        instance.proxy.attach_disk(
            target_dev,
            source,
            source_info=source_info,
            pool_type=pool_type,
            disk_type=disk_type,
            target_bus=bus,
            format_type=format_type,
            cache_mode=cache,
        )
    return _back(request, pk, "disks")


@require_POST
@superuser_only
@serialize_instance_mutation
def edit_volume(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    if "edit_volume" in request.POST:
        target_dev = request.POST.get("dev", "")

        new_path = request.POST.get("vol_path", "")
        shareable = bool(request.POST.get("vol_shareable", False))
        readonly = bool(request.POST.get("vol_readonly", False))
        disks = instance.proxy.get_disk_devices(config=True)
        current = next((disk for disk in disks if disk["dev"] == target_dev), {})
        new_bus = request.POST.get("vol_bus", current.get("bus"))
        serial = request.POST.get("vol_serial", "")
        format = request.POST.get("vol_format", "")
        cache = request.POST.get(
            "vol_cache", app_settings.INSTANCE_VOLUME_DEFAULT_CACHE
        )
        io = request.POST.get("vol_io_mode", app_settings.INSTANCE_VOLUME_DEFAULT_IO)
        discard = request.POST.get(
            "vol_discard_mode", app_settings.INSTANCE_VOLUME_DEFAULT_DISCARD
        )
        zeroes = request.POST.get(
            "vol_detect_zeroes", app_settings.INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES
        )
        # The form shows "None" (or nothing) for a disk without driver type.
        if format in ("", "None"):
            format = current.get("format") or ""

        invalid = invalid_disk_options(
            instance,
            bus=new_bus,
            cache=cache,
            io=io,
            discard=discard,
            zeroes=zeroes,
            # "": the disk has no driver type and keeps having none.
            format=format or None,
            serial=serial,
        )
        if not current:
            invalid.append("dev")
        if invalid:
            return reject_disk_options(request, pk, invalid)

        with audit_vm(request, instance, f"edit disk {target_dev}"):
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
            messages.success(
                request,
                _(
                    "Volume changes are applied. "
                    + "But it will be activated after shutdown"
                ),
            )
        else:
            messages.success(request, _("Volume is changed successfully."))

    return _back(request, pk, "disks")


@require_POST
@superuser_only
@serialize_compute_mutation
def delete_vol(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    dev = request.POST.get("dev", "")

    # Resolve the volume from the VM's own XML; never trust the posted
    # storage/name, which could point at any volume on the compute.
    disk = next((d for d in instance.disks if d["dev"] == dev), None)
    if disk is None or not disk["storage"] or not disk["image"]:
        messages.error(
            request,
            _("Disk %(dev)s is not a storage volume of this instance") % {"dev": dev},
        )
        return _back(request, pk, "disks")
    # the page lists the persistent disks: delete only a volume both definitions use there
    if not any(d["dev"] == dev and d["path"] == disk["path"] for d in instance.config_disks):
        messages.error(
            request,
            _("Disk %(dev)s has a pending change; delete it once the VM is shut down") % {"dev": dev},
        )
        return _back(request, pk, "disks")

    conn_delete = wvmStorage(
        instance.compute.hostname,
        instance.compute.login,
        instance.compute.password,
        instance.compute.type,
        disk["storage"],
    )

    if disk["path"] in instance.proxy.paths_used_by_other_domains():
        messages.error(
            request,
            _("Volume %(vol)s is used by another VM; detach it instead") % {"vol": disk["image"]},
        )
        return _back(request, pk, "disks")

    volume = f"{disk['storage']}/{disk['image']}"
    with audit_vm(request, instance, f"detach disk {dev}"):
        instance.proxy.detach_disk(dev)
    # Never delete a volume the guest may still be writing to.
    if not instance.proxy.wait_disk_detached(dev):
        failed_vm(request, instance, f"delete volume {volume}", "the guest has not released the disk")
        messages.warning(
            request,
            _("The guest has not released disk %(dev)s yet; volume %(vol)s was kept. "
              "Delete it from the storage pool once the VM is shut down.")
            % {"dev": dev, "vol": disk["image"]},
        )
        return _back(request, pk, "disks")
    try:
        with audit_vm(request, instance, f"delete volume {volume}"):
            conn_delete.del_volume(disk["image"])
    except util.OperationError as err:  # a file of the VM's own snapshots
        messages.warning(
            request,
            _("Disk %(dev)s was detached, but its volume was kept: %(err)s") % {"dev": dev, "err": err},
        )
    return _back(request, pk, "disks")


@require_POST
@superuser_only
@serialize_instance_mutation
def detach_vol(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    dev = request.POST.get("dev", "")
    with audit_vm(request, instance, f"detach disk {dev}"):
        instance.proxy.detach_disk(dev)

    return _back(request, pk, "disks")


@require_POST
@superuser_only
@serialize_instance_mutation
def add_cdrom(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    bus = request.POST.get("bus", "ide" if instance.machine == "pc" else "sata")
    invalid = invalid_disk_options(instance, bus=bus)
    if invalid:
        return reject_disk_options(request, pk, invalid)

    target = utils.get_new_disk_dev(
        instance.media + instance.config_media, instance.disks + instance.config_disks, bus
    )
    with audit_vm(request, instance, f"add CD-ROM {target}"):
        instance.proxy.attach_disk(
            target,
            "",
            disk_device="cdrom",
            cache_mode="none",
            target_bus=bus,
            readonly=True,
        )

    return _back(request, pk, "disks")


@require_POST
@superuser_only
@serialize_instance_mutation
def detach_cdrom(request, pk, dev):
    instance = get_instance(request.user, pk, perm_type="change")
    with audit_vm(request, instance, f"remove CD-ROM {dev}"):
        instance.proxy.detach_disk(dev)

    return _back(request, pk, "disks")


@require_POST
@superuser_only
@serialize_instance_mutation
def unmount_iso(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    dev = request.POST.get("umount_iso", "")
    try:
        with audit_vm(request, instance, f"eject media from {dev}"):
            instance.proxy.umount_iso(dev)
    except libvirtError as err:
        messages.error(request, err)
    return redirect(same_origin_referer(request, reverse("instances:instance", args=[pk])) + "#disks")


@require_POST
@superuser_only
@serialize_instance_mutation
def mount_iso(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    image = request.POST.get("media", "")
    dev = request.POST.get("mount_iso", "")
    try:
        with audit_vm(request, instance, f"insert media {image} into {dev}"):
            instance.proxy.mount_iso(dev, image)
    except libvirtError as err:
        messages.error(request, err)
    return redirect(same_origin_referer(request, reverse("instances:instance", args=[pk])) + "#disks")


@require_POST
def snapshot(request, pk):
    return _snapshot_job(request, pk, "snapshot.create",
                         {"name": request.POST.get("name", ""), "description": request.POST.get("description", "")})


@require_POST
@serialize_instance_mutation
def delete_snapshot(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    if not request.user.has_perm("instances.snapshot_instances"):
        raise PermissionDenied
    snap_name = request.POST.get("name", "")
    try:
        with audit_vm(request, instance, f"delete snapshot {snap_name}"):
            instance.proxy.snapshot_delete(snap_name)
    except libvirtError as err:
        messages.error(request, _("Snapshot was not deleted: %(err)s") % {"err": error_text(request, err)})
    return _back(request, pk, "managesnapshot")


@require_POST
def revert_snapshot(request, pk):
    return _snapshot_job(request, pk, "snapshot.revert", {"name": request.POST.get("name", "")})


@require_POST
def create_external_snapshot(request, pk):
    return _snapshot_job(request, pk, "snapshot.create",
                         {"name": request.POST.get("name", ""), "description": request.POST.get("description", ""),
                          "external": True, "memory": request.POST.get("memory") == "on",
                          "quiesce": request.POST.get("quiesce") == "on"})


@require_POST
def revert_external_snapshot(request, pk):
    return _snapshot_job(request, pk, "snapshot.revert", {"name": request.POST.get("name", ""), "external": True})


def _snapshot_job(request, pk, kind, params):
    """Queue a snapshot job on the VM: the job panel shows it; refusals become messages."""
    get_instance(request.user, pk, perm_type="change")
    if not request.user.has_perm("instances.snapshot_instances"):
        raise PermissionDenied
    try:
        op = jobs.submit(kind, request.user, {"instance": pk, **params}, request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        messages.error(request, busy_message(busy, request.user))
    except jobs.SubmissionConflict as err:
        messages.error(request, str(err))
    except libvirtError as err:
        messages.error(request, error_text(request, err))
    else:
        jobs.remember_job(request, op)
    return _back(request, pk, "managesnapshot")


@require_POST
def delete_external_snapshot(request, pk):
    return _snapshot_job(request, pk, "snapshot.delete", {"name": request.POST.get("name", "")})


@require_POST
@superuser_only
@serialize_instance_mutation
def set_vcpu(request, pk):
    instance = get_instance(request.user, pk)
    id = request.POST.get("id", "")
    enabled = request.POST.get("set_vcpu", "") == "True"
    with audit_vm(request, instance, f"{'enable' if enabled else 'disable'} vCPU {id}"):
        instance.proxy.set_vcpu(id, 1 if enabled else 0)
    return _back(request, pk, "resize")


@require_POST
@superuser_only
@serialize_instance_mutation
def set_vcpu_hotplug(request, pk):
    instance = get_instance(request.user, pk)
    status = True if request.POST.get("vcpu_hotplug", "False") == "True" else False
    with audit_vm(request, instance, f"{'enable' if status else 'disable'} vCPU hot-plug"):
        instance.proxy.set_vcpu_hotplug(status)
    return _back(request, pk, "resize")


@require_POST
@superuser_only
@serialize_instance_mutation
def set_autostart(request, pk):
    instance = get_instance(request.user, pk)
    with audit_vm(request, instance, "enable autostart"):
        instance.proxy.set_autostart(1)
    return _back(request, pk, "boot_opt")


@require_POST
@superuser_only
@serialize_instance_mutation
def unset_autostart(request, pk):
    instance = get_instance(request.user, pk)
    with audit_vm(request, instance, "disable autostart"):
        instance.proxy.set_autostart(0)
    return _back(request, pk, "boot_opt")


@require_POST
@superuser_only
@serialize_instance_mutation
def set_bootmenu(request, pk):
    instance = get_instance(request.user, pk)
    with audit_vm(request, instance, "enable boot menu"):
        instance.proxy.set_bootmenu(1)
    return _back(request, pk, "boot_opt")


@require_POST
@superuser_only
@serialize_instance_mutation
def unset_bootmenu(request, pk):
    instance = get_instance(request.user, pk)
    with audit_vm(request, instance, "disable boot menu"):
        instance.proxy.set_bootmenu(0)
    return _back(request, pk, "boot_opt")


@require_POST
@superuser_only
@serialize_instance_mutation
def set_bootorder(request, pk):
    instance = get_instance(request.user, pk)
    bootorder = request.POST.get("bootorder", "")
    if bootorder:
        order_list = {}
        for idx, val in enumerate(bootorder.split(",")):
            dev_type, dev = val.split(":", 1)
            order_list[idx] = {"type": dev_type, "dev": dev}
        try:
            with audit_vm(request, instance, "change boot order"):
                instance.proxy.set_bootorder(order_list)
        except util.OperationError as err:
            messages.error(request, err)
            return _back(request, pk, "boot_opt")

        if not instance.proxy.get_status() == 5:
            messages.success(
                request,
                _(
                    "Boot menu changes applied. "
                    + "But it will be activated after shutdown"
                ),
            )
        else:
            messages.success(request, _("Boot order changed successfully."))
    return _back(request, pk, "boot_opt")


@require_POST
@superuser_only
@serialize_instance_mutation
def change_xml(request, pk):
    """
    The XML editor's dialog: without confirm, the lines the edited XML changes
    in the persistent definition, to review; with confirm, the edited XML is
    defined. A running VM uses it at its next start.
    Only over the definition the editor was opened with (base), so a change
    made since is not overwritten, and only with the VM's UUID, by which
    libvirt finds the VM to define. A form posts its line breaks as CRLF. A
    refusal comes back to the dialog and the edited XML stays in the editor.
    """
    instance = get_instance(request.user, pk)
    new_xml = request.POST.get("inst_xml", "").replace("\r\n", "\n")
    if not new_xml.strip():
        return JsonResponse({"error": _("The XML is empty")}, status=400)
    try:
        uuid = util.get_xml_path(new_xml, "/domain/uuid")
    except util.etree.Error as err:
        return JsonResponse({"error": _("The XML is not well-formed: %(error)s") % {"error": err}}, status=400)
    if (uuid or "").strip().lower() != instance.uuid:
        return JsonResponse({"error": _("The XML must keep the VM's UUID %(uuid)s.") % {"uuid": instance.uuid}},
                            status=400)
    current = instance.inst_xml
    if request.POST.get("base", "").replace("\r\n", "\n") != current:
        return JsonResponse({"error": _("The definition has changed since the editor was opened. "
                                         "Reload the page to edit the current one.")}, status=409)
    if "confirm" not in request.POST:
        diff = difflib.unified_diff(current.splitlines(), new_xml.splitlines(), "current", "new", lineterm="")
        return JsonResponse({"diff": list(diff)})
    shut_off = instance.proxy.get_status() == 5
    try:
        with audit_vm(request, instance, "change XML"):
            instance.proxy._defineXML(new_xml)
    except libvirtError as err:
        return JsonResponse({"error": error_text(request, err)}, status=400)
    if shut_off:
        messages.success(request, _("The XML definition was saved."))
    else:
        messages.success(request, _("The XML definition was saved; the VM uses it from its next start."))
    return JsonResponse({"saved": True})

@require_POST
@superuser_only
@serialize_instance_mutation
def set_guest_agent(request, pk):
    instance = get_instance(request.user, pk)
    status = request.POST.get("guest_agent")
    if status == "True":
        with audit_vm(request, instance, "add guest agent channel"):
            instance.proxy.add_guest_agent()
    if status == "False":
        with audit_vm(request, instance, "remove guest agent channel"):
            instance.proxy.remove_guest_agent()
    return _back(request, pk, "options")


@require_POST
@superuser_only
@serialize_instance_mutation
def set_video_model(request, pk):
    instance = get_instance(request.user, pk)
    video_model = request.POST.get("video_model", "vga")
    with audit_vm(request, instance, f"set video model {video_model}"):
        instance.proxy.set_video_model(video_model)
    return _back(request, pk, "options")


@require_POST
@superuser_only
@serialize_instance_mutation
def change_network(request, pk):
    instance = get_instance(request.user, pk)
    back = same_origin_referer(request, reverse("instances:instance", args=[pk])) + "#network"

    # Each NIC has its own form; its fields end with that NIC's index.
    nums = [key[len("net-old-mac-"):] for key in request.POST if key.startswith("net-old-mac-")]
    if len(nums) != 1:
        messages.error(request, _("Select one network interface to change"))
        return redirect(back)
    num = nums[0]
    old_mac = request.POST[f"net-old-mac-{num}"]
    mac = request.POST.get(f"net-mac-{num}", "").strip() or old_mac
    try:
        util.validate_macaddr(mac)
    except ValueError as err:
        messages.error(request, err)
        return redirect(back)

    (source, source_type) = utils.get_network_tuple(request.POST.get(f"net-source-{num}", ""))
    try:
        with audit_vm(request, instance, f"change interface {old_mac}"):
            if source_type == "iface":
                iface = wvmInterface(
                    instance.compute.hostname,
                    instance.compute.login,
                    instance.compute.password,
                    instance.compute.type,
                    source,
                )
                source_type = iface.get_type()
            instance.proxy.change_network(
                old_mac,
                mac,
                source,
                source_type,
                request.POST.get(f"net-model-{num}"),
                request.POST.get(f"net-nwfilter-{num}", ""),
            )
    except libvirtError as err:
        messages.error(request, err)
        return redirect(back)

    if instance.proxy.get_status() != 5:
        messages.success(request, _("Network Device Config is changed. Please shutdown instance to activate."))
    else:
        messages.success(request, _("Network device changed"))
    return redirect(back)


@require_POST
@superuser_only
@serialize_instance_mutation
def add_network(request, pk):
    instance = get_instance(request.user, pk)

    network = request.POST.get("add-net-network")
    if not network:
        messages.error(request, _("No network selected"))
        return _back(request, pk, "network")
    mac = request.POST.get("add-net-mac")
    nwfilter = request.POST.get("add-net-nwfilter")
    (source, source_type) = utils.get_network_tuple(network)
    model = request.POST.get("add-net-model")

    with audit_vm(request, instance, f"add interface on {source}"):
        if source_type == "iface":
            iface = wvmInterface(
                instance.compute.hostname,
                instance.compute.login,
                instance.compute.password,
                instance.compute.type,
                source,
            )
            source_type = iface.get_type()
        instance.proxy.add_network(mac, source, source_type, model=model, nwfilter=nwfilter)
    return _back(request, pk, "network")


@require_POST
@superuser_only
@serialize_instance_mutation
def delete_network(request, pk):
    instance = get_instance(request.user, pk)
    mac_address = request.POST.get("delete_network", "")

    with audit_vm(request, instance, f"remove interface {mac_address}"):
        instance.proxy.delete_network(mac_address)
    return _back(request, pk, "network")


def _host_devices(instance):
    """The host's PCI and USB devices, each with why it cannot be given to
    the VM (pci_problems, hostdev_problems; none: it can). A USB device is
    named by its address when the host has more than one of its model, else
    by model; a PCI device is checked alone on a running VM, as it is
    hot-plugged, and with the managed PCI devices of the VM's next start on
    a shut-off one, as libvirt takes them from the host along with it."""
    pci, usb = node_devices(instance.proxy)
    own_pci = instance.proxy.get_hostdevs()[1]
    # libvirt takes a hot-plugged device alone from the host, and a group's managed devices as the VM starts
    if instance.proxy.instance.isActive():
        managed = set()
    else:
        managed = {row["address"] for row in own_pci if row["managed"] and row["next"]}
    by_address = {device["address"]: device for device in pci}
    for device in pci:
        device["problems"] = pci_problems(instance.name, device, by_address, managed | {device["address"]})
        if device["address"] in {row["address"] for row in own_pci}:
            device["problems"].append(_("The VM has it"))
    for device in usb:
        address = (device["bus"], device["device"]) if device["same_model"] else None
        device["selector"] = (*device["model"], address)
        device["problems"] = hostdev_problems(instance.name, pci, [device], set(), [device["selector"]])
        if instance.name in device["vms"]:
            device["problems"].append(_("The VM has it"))
    return pci, usb


@superuser_only
def host_devices(request, pk):
    """The add forms of the Host devices tab, loaded when the tab opens:
    their choices scan every VM of the host."""
    instance = get_instance(request.user, pk)
    try:
        pci, usb = _host_devices(instance)
        domain = instance.proxy.instance
        state = domain.info()[0]
        context = {"instance": instance, "host_pci": pci, "host_usb": usb, "running": state == VIR_DOMAIN_RUNNING,
                   # paused, or with a saved state the VM would start from without the change
                   "pci_frozen": state not in (VIR_DOMAIN_RUNNING, VIR_DOMAIN_SHUTOFF) or domain.hasManagedSaveImage(0)}
    except libvirtError as err:
        context = {"instance": instance, "error": err}
    return render(request, "instances/host_devices_form.html", context)


@require_POST
@superuser_only
@serialize_compute_mutation
def add_usb_hostdev(request, pk):
    """Gives the VM a USB device of its host; checked under the compute's
    claim, so no other VM gets it meanwhile."""
    instance = get_instance(request.user, pk)
    chosen = request.POST.get("usb_device", "")
    device = next((d for d in _host_devices(instance)[1] if f"{d['bus']}/{d['device']}" == chosen), None)
    if device is None:
        messages.error(request, _("The host has no USB device %(device)s") % {"device": chosen})
    elif device["problems"]:
        messages.error(request, "; ".join(device["problems"]))
    else:
        vendor, product, address = device["selector"]
        with audit_vm(request, instance, f"add USB device {device['ids']} ({device['product']})"):
            instance.proxy.add_usb_hostdev(vendor, product, address)
    return _back(request, pk, "hostdevs")


@require_POST
@superuser_only
@serialize_compute_mutation
def add_pci_hostdev(request, pk):
    """Gives the VM a PCI device of its host, hot-plugged while it runs;
    checked under the compute's claim, so no other VM gets it or its IOMMU
    group meanwhile."""
    instance = get_instance(request.user, pk)
    chosen = request.POST.get("pci_device", "")
    device = next((d for d in _host_devices(instance)[0] if d["address"] == chosen), None)
    if device is None:
        messages.error(request, _("The host has no PCI device %(device)s") % {"device": chosen})
    elif device["problems"]:
        messages.error(request, "; ".join(device["problems"]))
    else:
        with audit_vm(request, instance, f"add PCI device {device['address']} ({device['product']})"):
            instance.proxy.add_pci_hostdev(device["address"])
    return _back(request, pk, "hostdevs")


@require_POST
@superuser_only
@serialize_instance_mutation
def delete_pci_hostdev(request, pk):
    instance = get_instance(request.user, pk)
    address = request.POST.get("address", "")
    with audit_vm(request, instance, f"remove PCI device {address}") as entry:
        if instance.proxy.delete_pci_hostdev(address):
            entry.action = f"request the removal of PCI device {address}"
            messages.warning(request, _("Removal of PCI device %(address)s requested: the guest has not let it go yet; "
                                        "it stays in the running VM until it does or the VM stops.") % {"address": address})
    return _back(request, pk, "hostdevs")


@require_POST
@superuser_only
@serialize_instance_mutation
def delete_usb_hostdev(request, pk):
    instance = get_instance(request.user, pk)
    vendor, product = request.POST.get("vendor", ""), request.POST.get("product", "")
    bus, _sep, device = request.POST.get("address", "").partition("/")
    address = (int(bus), int(device)) if bus.isdigit() and device.isdigit() else None
    with audit_vm(request, instance, f"remove USB device {vendor[2:]}:{product[2:]}"):
        instance.proxy.delete_usb_hostdev((vendor, product, address))
    return _back(request, pk, "hostdevs")


@require_POST
@superuser_only
@serialize_instance_mutation
def set_link_state(request, pk):
    instance = get_instance(request.user, pk)

    mac_address = request.POST.get("mac", "")
    state = request.POST.get("set_link_state")
    state = "down" if state == "up" else "up"
    with audit_vm(request, instance, f"set link {state} on interface {mac_address}"):
        instance.proxy.set_link_state(mac_address, state)
    return _back(request, pk, "network")


@require_POST
@superuser_only
@serialize_instance_mutation
def set_qos(request, pk):
    instance = get_instance(request.user, pk)

    qos_dir = request.POST.get("qos_direction", "")
    average = request.POST.get("qos_average") or 0
    peak = request.POST.get("qos_peak") or 0
    burst = request.POST.get("qos_burst") or 0
    mac_key = [key for key in request.POST if "mac" in key]
    mac = request.POST.get(mac_key[0]) if mac_key else None
    if not mac or qos_dir not in ("inbound", "outbound"):
        messages.error(request, _("Select a network interface and a QoS direction"))
        return _back(request, pk, "network")
    if not all(_is_int(rate) for rate in (average, peak, burst)):
        messages.error(request, _("QoS rates must be whole numbers"))
        return _back(request, pk, "network")

    with audit_vm(request, instance, f"set {qos_dir} QoS on interface {mac}"):
        instance.proxy.set_qos(mac, qos_dir, average, peak, burst)
    if instance.proxy.get_status() == 5:
        messages.success(
            request, _("%(qos_dir)s QoS is set") % {"qos_dir": qos_dir.capitalize()}
        )
    else:
        messages.success(
            request,
            _("%(qos_dir)s QoS is set. A running VM gets it after it is powered off and on.")
            % {"qos_dir": qos_dir.capitalize()},
        )

    return _back(request, pk, "network")


@require_POST
@superuser_only
@serialize_instance_mutation
def unset_qos(request, pk):
    instance = get_instance(request.user, pk)
    qos_dir = request.POST.get("qos_direction", "")
    mac = request.POST.get("net-mac")
    if not mac or qos_dir not in ("inbound", "outbound"):
        messages.error(request, _("Select a network interface and a QoS direction"))
        return _back(request, pk, "network")
    with audit_vm(request, instance, f"remove {qos_dir} QoS from interface {mac}"):
        instance.proxy.unset_qos(mac, qos_dir)

    if instance.proxy.get_status() == 5:
        messages.success(
            request, _("%(qos_dir)s QoS is deleted") % {"qos_dir": qos_dir.capitalize()}
        )
    else:
        messages.success(
            request,
            _("%(qos_dir)s QoS is deleted. A running VM keeps the old limit until it is powered off and on.")
            % {"qos_dir": qos_dir.capitalize()},
        )
    return _back(request, pk, "network")


@require_POST
@superuser_only
def add_owner(request, pk):
    instance = get_instance(request.user, pk)
    user_id = request.POST.get("user_id", "")
    if not user_id.isdigit():
        raise Http404
    user = get_object_or_404(User, pk=user_id)

    check_inst = 0

    if app_settings.ALLOW_INSTANCE_MULTIPLE_OWNER == "False":
        check_inst = UserInstance.objects.filter(instance=instance).count()

    action = f"add owner {user.username}"
    if check_inst > 0:
        failed_vm(request, instance, action, "only one owner is allowed")
        messages.error(
            request, _("Only one owner is allowed and the one already added")
        )
    else:
        with audit_vm(request, instance, action) as entry:
            entry.skip = not UserInstance.objects.get_or_create(instance=instance, user=user)[1]
        if entry.skip:
            messages.warning(request, _("%(user)s is already an owner") % {"user": user})
    return _back(request, pk, "users")


@require_POST
@superuser_only
def del_owner(request, pk):
    instance = get_instance(request.user, pk)
    userinstance_id = request.POST.get("userinstance", "")
    if not userinstance_id.isdigit():
        raise Http404
    userinstance = get_object_or_404(UserInstance, pk=userinstance_id, instance=instance)
    with audit_vm(request, instance, f"remove owner {userinstance.user.username}"):
        userinstance.delete()
    return _back(request, pk, "users")


# Buses for the empty CD-ROM of a new VM: fdc and virtio have no ejectable
# media, and libvirt refuses an empty usb disk.
CDROM_BUSES = ("ide", "sata", "scsi")


def _clone_source(user, pk):
    """Cloning copies the source disks, so it needs change permission on the
    source VM. Templates are meant to be deployed from, so viewing is enough."""
    instance = get_instance(user, pk)
    if not instance.is_template:
        instance = get_instance(user, pk, perm_type="change")
    return instance


@require_POST
@permission_required("instances.clone_instances", raise_exception=True)
@serialize_user_quota
def clone(request, pk):
    _clone_source(request.user, pk)  # 403/404 first
    try:
        op = jobs.submit("instance.clone", request.user, {"instance": pk, **request.POST.dict()},
                         request.POST.get("submission_key", ""))
    except claims.Busy as busy:
        return _busy(request, pk, busy)
    except (jobs.SubmissionConflict, libvirtError, ValueError) as err:
        messages.error(request, error_text(request, err))
    else:
        jobs.remember_job(request, op)
    return redirect(reverse("instances:instance", args=[pk]))


@require_POST
@serialize_instance_mutation
def update_console(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")

    if not utils.can_manage_console(request.user, instance):
        raise PermissionDenied
    form = ConsoleForm(request.POST, instance=instance, can_set_listener=request.user.is_superuser)
    if form.is_valid() and form.cleaned_data["console_type"] not in ("", instance.console_type):
        with audit_vm(request, instance, f"set console type {form.cleaned_data['console_type']}"):
            instance.proxy.set_console_type(form.cleaned_data["console_type"])
    # the other fields are VNC settings; a new VNC console gets them too
    if form.is_valid() and form.cleaned_data["console_type"] != "pty":
        if (
            "generate_password" in form.changed_data
            or "clear_password" in form.changed_data
            or "password" in form.changed_data
        ):
            if form.cleaned_data["generate_password"]:
                password = randomPasswd()
            elif form.cleaned_data["clear_password"]:
                password = ""
            else:
                password = form.cleaned_data["password"]

            # A console that listens beyond localhost (set by an
            # administrator) keeps its password unless an administrator
            # removes it. The definition being changed is the persistent one.
            if (
                not password
                and not request.user.is_superuser
                and not instance.proxy.console_listens_locally()
            ):
                messages.error(
                    request,
                    _("The console listens beyond localhost; only an administrator can remove its password."),
                )
            else:
                try:
                    with audit_vm(request, instance, "set console password" if password else "remove console password"):
                        if not instance.proxy.set_console_passwd(password):
                            raise util.OperationError("The VM has no graphics device")
                except util.OperationError:
                    msg = _(
                        "Error setting console password. "
                        + "You should check that your instance have an graphic device."
                    )
                    messages.error(request, msg)

        if "keymap" in form.changed_data:
            # "auto" removes the keymap: the client's keys go through as they are
            keymap = form.cleaned_data["keymap"]
            # False: no graphics device, nothing changed
            with audit_vm(request, instance, "remove console keymap" if keymap == "auto" else f"set console keymap {keymap}") as entry:
                entry.skip = instance.proxy.set_console_keymap(keymap) is False

        if "listen_on" in form.changed_data:
            with audit_vm(request, instance, f"set console listen address {form.cleaned_data['listen_on']}") as entry:
                entry.skip = instance.proxy.set_console_listener_addr(form.cleaned_data["listen_on"]) is False
    if not form.is_valid():
        messages.error(request, _("Console settings were not saved: %(errors)s") % {"errors": form.errors.as_text()})

    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id]) + "#vncsettings"
    )


@require_POST
@serialize_user_quota
@serialize_instance_mutation
def change_options(request, pk):
    instance = get_instance(request.user, pk, perm_type="change")
    try:
        userinstance = instance.userinstance_set.get(user=request.user)
    except UserInstance.DoesNotExist:
        userinstance = UserInstance(is_change=False)

    if request.user.is_superuser or userinstance.is_change:
        # Only superusers and staff may (un)mark templates. The
        # checkbox is disabled for everyone else, and a disabled checkbox is
        # not submitted, so for them the flag must be left alone.
        if request.user.is_superuser or request.user.is_staff:
            is_template = bool(request.POST.get("is_template", False))
            # A template is not counted and cannot be started: making it a
            # VM again adds it to the owner's usage, so the quota applies.
            if instance.is_template and not is_template and not request.user.is_superuser:
                disk_sum = sum(int(disk.get("size") or 0) >> 30 for disk in instance.disks)
                quota_msg = utils.check_user_quota(request.user, 1, instance.vcpu, instance.memory, disk_sum)
                if quota_msg:
                    messages.error(request, quota_refused(quota_msg, _(
                        "User %(quota_msg)s quota reached, '%(instance_name)s' stays a template!"
                    ) % {"quota_msg": quota_msg, "instance_name": instance.name}))
                    is_template = True
            instance.is_template = is_template
            instance.save(update_fields=["is_template"])

        options = {}
        for post in request.POST:
            if post in ["title", "description"]:
                options[post] = request.POST.get(post, "")
        with audit_vm(request, instance, "edit options"):
            instance.proxy.set_options(options)
    return get_safe_redirect(
        request, default=reverse("instances:instance", args=[instance.id]) + "#options"
    )


def getvvfile(request, pk):
    instance = get_instance(request.user, pk)
    # The .vv file contains the VNC password: same rule as the console.
    if not utils.can_open_console(request.user, instance):
        raise PermissionDenied
    response = HttpResponse(
        content="",
        content_type="application/x-virt-viewer",
        status=200,
        reason=None,
        charset="utf-8",
    )
    # the VM found by its UUID; the stored name may be stale
    with audit_vm(request, instance, "download console file"), instance.proxy.cached_reads() as proxy:
        listen = proxy.get_console_listener_addr()
        response.writelines("[virt-viewer]\n")
        response.writelines(f"type={proxy.get_console_type()}\n")
        response.writelines(f"host={proxy.host if listen == '0.0.0.0' else listen}\n")
        response.writelines(f"port={proxy.get_console_port()}\n")
        response.writelines(f"title={proxy.instance.name()}\n")
        response.writelines(f"password={proxy.get_console_passwd() or ''}\n")
    response.writelines("enable-usbredir=1\n")
    response.writelines("disable-effects=all\n")
    response.writelines("secure-attention=ctrl+alt+ins\n")
    response.writelines("release-cursor=ctrl+alt\n")
    response.writelines("fullscreen=1\n")
    response.writelines("delete-this-file=1\n")
    response["Content-Disposition"] = 'attachment; filename="console.vv"'
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
    supported_arch = [
        "x86_64",
        "i686",
        "aarch64",
        "armv7l",
        "ppc64",
        "ppc64le",
        "s390x",
    ]
    hypervisors = [hpv for hpv in all_hypervisors.keys() if hpv in supported_arch]
    default_machine = app_settings.INSTANCE_MACHINE_DEFAULT_TYPE
    default_arch = app_settings.INSTANCE_ARCH_DEFAULT_TYPE

    # a refused definition comes back in the editor, its reason beside it
    xml_error = None
    if request.method == "POST" and "create_xml" in request.POST:
        xml = request.POST.get("dom_xml", "")
        try:
            name = util.get_xml_path(xml, "/domain/name")
            if not name:
                xml_error = _("The XML has no name")
            elif name in instances:
                xml_error = _("A virtual machine with this name already exists")
            else:
                with libvirt_compute_lock(compute):
                    with audit(request, compute, f"VM {name}", "define from XML", instance=name) as entry:
                        conn._defineXML(xml)
                        utils.refr(compute)
                        instance = compute.instance_set.get(name=name)
                        entry.uuid = instance.uuid
                return redirect(reverse("instances:instance", args=[instance.id]))
        except util.etree.Error as err:
            xml_error = _("The XML is not well-formed: %(error)s") % {"error": err}
        except libvirtError as err:
            xml_error = _("libvirt Error - %(exception)s") % {"exception": error_text(request, err)}

    return render(request, "create_instance_w1.html", locals())


# the create form's disk sources: (value, title, help)
DISK_SOURCES = [
    ("new", _("New disk"), _("An empty disk of the size you set")),
    ("existing", _("Existing volumes"), _("Volumes already in a pool")),
    ("template", _("Clone from template"), _("A copy of a template volume")),
]


def refused_lists(post):
    """The volume pool, volumes and networks of a refused create form as
    submitted, for the page to rebuild them."""
    images = post["images"].split(",") if post.get("images") else []
    networks = post["networks"].split(",") if post.get("networks") else []
    macs = post.get("mac", "").split(",")
    return {
        "pool": post.get("storage-control", ""),
        "disks": [{"volume": image, "device": post.get(f"device{i}", ""), "bus": post.get(f"bus{i}", "")}
                  for i, image in enumerate(images)],
        "networks": [{"name": network, "mac": macs[i] if i < len(macs) else ""}
                     for i, network in enumerate(networks)],
    }


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
    flavors = Flavor.objects.filter().order_by("id")
    appsettings = AppSettings.objects.all()
    vm_form = None
    flavor_form = FlavorForm()
    refused = False
    disk_sources = DISK_SOURCES
    disk_source = request.POST.get("disk_source", "new")
    if disk_source not in [value for value, _title, _help in DISK_SOURCES]:
        disk_source = "new"

    try:
        conn = wvmCreate(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type
        )

        default_firmware = app_settings.INSTANCE_FIRMWARE_DEFAULT_TYPE
        default_cpu_mode = app_settings.INSTANCE_CPU_DEFAULT_MODE
        instances = conn.get_instances()
        videos = conn.get_video_models(arch, machine)
        default_video = app_settings.INSTANCE_VIDEO_DEFAULT_TYPE
        cache_modes = sorted(conn.get_cache_modes().items())
        default_cache = app_settings.INSTANCE_VOLUME_DEFAULT_CACHE
        default_io = app_settings.INSTANCE_VOLUME_DEFAULT_IO
        default_zeroes = app_settings.INSTANCE_VOLUME_DEFAULT_DETECT_ZEROES
        default_discard = app_settings.INSTANCE_VOLUME_DEFAULT_DISCARD
        default_disk_format = app_settings.INSTANCE_VOLUME_DEFAULT_FORMAT
        default_disk_owner_uid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
        default_disk_owner_gid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)
        default_scsi_disk_model = app_settings.INSTANCE_VOLUME_DEFAULT_SCSI_CONTROLLER
        listener_addr = settings.QEMU_CONSOLE_LISTENER_ADDRESSES
        disk_devices = conn.get_disk_device_types(arch, machine)
        disk_buses = conn.get_disk_bus_types(arch, machine)
        cdrom_buses = [bus for bus in disk_buses if bus in CDROM_BUSES]
        default_bus = app_settings.INSTANCE_VOLUME_DEFAULT_BUS
        networks = sorted(conn.get_networks())
        nwfilters = conn.get_nwfilters()
        net_models_host = conn.get_network_models()
        default_nic_type = app_settings.INSTANCE_NIC_DEFAULT_TYPE
        storages = sorted(conn.get_storages(only_actives=True))
        default_cdrom = app_settings.INSTANCE_CDROM_ADD
        input_device_buses = ["default", "virtio", "usb"]
        default_input_device_bus = app_settings.INSTANCE_INPUT_DEFAULT_DEVICE

        dom_caps = conn.get_dom_capabilities(arch, machine)
        caps = conn.get_capabilities(arch)

        virtio_support = conn.is_supports_virtio(arch, machine)
        # Add BIOS
        label = conn.label_for_firmware_path(arch, None)
        if label:
            firmwares.append(label)
        # Add UEFI
        loader_path = conn.find_uefi_path_for_arch(arch, machine)
        label = conn.label_for_firmware_path(arch, loader_path)
        if label:
            firmwares.append(label)
        firmwares = list(set(firmwares))

        if not storages:
            raise util.OperationError(_("You haven't defined any storage pools"))
        if not networks:
            raise util.OperationError(_("You haven't defined any network pools"))

        vm_form = NewVMForm(initial={
            # a default this host does not offer is no choice: the select asks for one
            "vcpu": 1, "memory": 512, "firmware": default_firmware,
            "vcpu_mode": default_cpu_mode if default_cpu_mode in cpu_choices(dom_caps) else "",
            "cache_mode": default_cache, "net_model": default_nic_type, "listener_addr": "0.0.0.0",
            "add_cdrom": default_cdrom, "add_input": default_input_device_bus, "video": default_video,
            "qemu_ga": True, "virtio": bool(virtio_support),
        })

        if conn:
            if request.method == "POST":
                if "create" in request.POST:
                    # the submitted form comes back bound if the page shows it again
                    form = vm_form = NewVMForm(request.POST)
                    refused = True
                    if form.is_valid():
                        data = form.cleaned_data
                        images = data["images"].split(",") if data["images"] else []
                        raw = {**data, "compute": compute.id, "arch": arch, "machine": machine,
                               "devices": [[request.POST.get(f"device{i}", ""), request.POST.get(f"bus{i}", "")]
                                           for i in range(len(images))]}
                        try:
                            op = jobs.submit("instance.create", request.user, raw,
                                             request.POST.get("submission_key", ""))
                        except claims.Busy as busy:
                            messages.error(request, busy_message(busy, request.user))
                        except jobs.SubmissionConflict as err:
                            messages.error(request, str(err))
                        else:
                            if op.params["machine"] != machine:
                                messages.warning(
                                    request,
                                    "Changing machine type from '%s' to 'q35' "
                                    "which is required for UEFI secure boot." % machine,
                                )
                            jobs.remember_job(request, op)
                            return redirect(reverse("instances", args=[compute.id]))
            conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    if refused:
        submitted_lists = refused_lists(request.POST)
        if disk_source == "template":
            template_restore = {"pool": request.POST.get("template_pool", ""), "template": request.POST.get("template", "")}
    return render(request, "create_instance_w2.html", locals())


def flavors_reply(request, flavor_form):
    return render(request, "create_flavors_reply.html",
                  {"flavors": Flavor.objects.order_by("id"), "flavor_form": flavor_form})


@superuser_only
def flavor_create(request):
    form = FlavorForm(request.POST or None)
    if form.is_valid():
        with audit(request, None, f"Flavor {form.cleaned_data['label']}", "add"):
            form.save()
        if from_script(request):
            return flavors_reply(request, FlavorForm())
        messages.success(request, _("Flavor Created"))
        return get_safe_redirect(request, default=reverse("instances:index"))
    if from_script(request):
        return flavors_reply(request, form)

    return render(
        request,
        "common/form.html",
        {"form": form, "title": _("Create Flavor")},
    )


@superuser_only
def flavor_update(request, pk):
    flavor = get_object_or_404(Flavor, pk=pk)
    subject, before = f"Flavor {flavor.label}", audit_snapshot(flavor)
    form = FlavorForm(request.POST or None, instance=flavor)
    if form.is_valid():
        with audit(request, None, subject, "change") as entry:
            form.save()
            fields = changed_fields(before, audit_snapshot(flavor))
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields
        messages.success(request, _("Flavor Updated"))
        return get_safe_redirect(request, default=reverse("instances:index"))

    return render(
        request,
        "common/form.html",
        {"form": form, "title": _("Update Flavor")},
    )


@superuser_only
def flavor_delete(request, pk):
    flavor = get_object_or_404(Flavor, pk=pk)
    if request.method == "POST":
        with audit(request, None, f"Flavor {flavor.label}", "delete"):
            flavor.delete()
        if from_script(request):
            return flavors_reply(request, FlavorForm())
        messages.success(request, _("Flavor Deleted"))
        return get_safe_redirect(request, default=reverse("instances:index"))

    return render(
        request,
        "common/confirm_delete.html",
        {"object": flavor, "consequence": _("Only the size template goes; VMs made from it keep their size.")},
    )
