import json
import socket

from accounts.models import UserInstance, UserSSHKey
from computes.models import Compute
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from libvirt import libvirtError
from vrtManager.instance import wvmInstance

OS_VERSIONS = ["latest", ""]
OS_UUID = "iid-dswebvirtcloud"


def os_index(request):
    """
    :param request:
    :return:
    """
    response = "\n".join(OS_VERSIONS)
    return HttpResponse(response)


def os_metadata_json(request, version):
    """
    :param request:
    :param version:
    :return:
    """

    if version == "latest":
        ip = get_client_ip(request)
        hostname = get_hostname_by_ip(ip)
        response = {"uuid": OS_UUID, "hostname": hostname}
        return HttpResponse(json.dumps(response))
    else:
        err = "Invalid version: %(version)s" % {"version": version}
        raise Http404(err)


def os_userdata(request, version):
    """
    :param request:
    :param version:
    :return:
    """
    if version == "latest":
        ip = get_client_ip(request)
        hostname = get_hostname_by_ip(ip)
        vname = hostname.split(".")[0]

        instance_keys = []
        userinstances = UserInstance.objects.filter(instance__name=vname)

        for ui in userinstances:
            keys = UserSSHKey.objects.filter(user=ui.user)
            for k in keys:
                instance_keys.append(k.keypublic)

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
    :return:
    """
    try:
        addrs = socket.gethostbyaddr(ip)
    except:
        addrs = [ip]
    return addrs[0]


def get_vdi_url(request, compute_id, vname):
    """
    :param request:
    :param vname:
    :return:
    """
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmInstance(
            compute.hostname, compute.login, compute.password, compute.type, vname
        )

        fqdn = get_hostname_by_ip(compute.hostname)
        url = f"{conn.get_console_type()}://{fqdn}:{conn.get_console_port()}"
        response = url
        return HttpResponse(response)
    except libvirtError:
        err = "Error getting VDI URL for %(name)s" % {"name": vname}
        raise Http404(err)
