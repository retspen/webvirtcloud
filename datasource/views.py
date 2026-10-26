import json
import socket

from accounts.models import UserInstance, UserSSHKey
from computes.models import Compute
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from instances.models import Instance
from instances.utils import can_open_console
from libvirt import libvirtError
from vrtManager.instance import wvmInstance

OS_VERSIONS = ["latest", ""]
OS_UUID = "iid-dswebvirtcloud"


# The cloud-init endpoints are fetched by booting VMs, which do not log in.
# They expose only a hostname and the public SSH keys of a VM's owners.


@login_not_required
def os_index(request):
    """
    :param request:
    :return:
    """
    response = "\n".join(OS_VERSIONS)
    return HttpResponse(response)


@login_not_required
def os_metadata_json(request, version):
    """
    :param request:
    :param version:
    :return:
    """

    if version == "latest":
        ip = get_client_ip(request)
        hostname = get_hostname_by_ip(ip) or ip
        response = {"uuid": OS_UUID, "hostname": hostname}
        return JsonResponse(response)
    else:
        err = "Invalid version: %(version)s" % {"version": version}
        raise Http404(err)


@login_not_required
def os_userdata(request, version):
    """
    :param request:
    :param version:
    :return:
    """
    if version == "latest":
        hostname = get_hostname_by_ip(get_client_ip(request))

        instance_keys = []
        # The VM is named by its address's reverse DNS entry; without one there
        # is no name (the address's first number is no VM's name). VM names
        # are not unique: with two VMs of this name, a user could put their key
        # into the other VM by naming theirs the same. No keys then.
        instances = list(Instance.objects.filter(name=hostname.split(".")[0])[:2]) if hostname else []
        if len(instances) == 1:
            for ui in UserInstance.objects.filter(instance=instances[0]):
                instance_keys += UserSSHKey.objects.filter(user=ui.user).values_list("keypublic", flat=True)
        # quoted, so a comment such as "it's: mine" stays one YAML string
        instance_keys = [json.dumps(key) for key in instance_keys]

        return render(request, "user_data", locals())
    else:
        err = "Invalid version: %(version)s" % {"version": version}
        raise Http404(err)


def get_client_ip(request):
    """
    :param request:
    :return:
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[-1].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def get_hostname_by_ip(ip):
    """
    :param ip:
    :return: the address's reverse DNS name, or None
    """
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:  # no reverse DNS entry or an invalid address
        return None


def get_vdi_url(request, compute_id, vname):
    """
    :param request:
    :param vname:
    :return:
    """
    compute = get_object_or_404(Compute, pk=compute_id)
    # The VDI URL points straight at the VM's console: same rule as the console.
    instance = Instance.objects.filter(compute=compute, name=vname).first()
    if instance is None or not can_open_console(request.user, instance):
        raise PermissionDenied

    try:
        conn = wvmInstance(
            compute.hostname, compute.login, compute.password, compute.type, vname, uuid=instance.uuid
        )

        fqdn = get_hostname_by_ip(compute.hostname) or compute.hostname
        url = f"{conn.get_console_type()}://{fqdn}:{conn.get_console_port()}"
        response = url
        return HttpResponse(response)
    except libvirtError:
        err = "Error getting VDI URL for %(name)s" % {"name": vname}
        raise Http404(err)
