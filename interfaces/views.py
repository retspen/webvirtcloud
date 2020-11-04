from django.contrib import messages
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse
from libvirt import libvirtError
from computes.models import Compute
from interfaces.forms import AddInterface
from vrtManager.interface import wvmInterface, wvmInterfaces
from admin.decorators import superuser_only


@superuser_only
def interfaces(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    ifaces_all = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmInterfaces(compute.hostname, compute.login, compute.password, compute.type)
        ifaces = conn.get_ifaces()
        try:
            netdevs = conn.get_net_devices()
        except:
            netdevs = ["eth0", "eth1"]

        for iface in ifaces:
            ifaces_all.append(conn.get_iface_info(iface))

        if request.method == "POST":
            if "create" in request.POST:
                form = AddInterface(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    conn.create_iface(
                        data["name"],
                        data["itype"],
                        data["start_mode"],
                        data["netdev"],
                        data["ipv4_type"],
                        data["ipv4_addr"],
                        data["ipv4_gw"],
                        data["ipv6_type"],
                        data["ipv6_addr"],
                        data["ipv6_gw"],
                        data["stp"],
                        data["delay"],
                    )
                    return HttpResponseRedirect(request.get_full_path())
                else:
                    for msg_err in form.errors.values():
                        messages.error(request, msg_err.as_text())
        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    return render(request, "interfaces.html", locals())


@superuser_only
def interface(request, compute_id, iface):
    """
    :param request:
    :param compute_id:
    :param iface:
    :return:
    """

    ifaces_all = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmInterface(compute.hostname, compute.login, compute.password, compute.type, iface)
        start_mode = conn.get_start_mode()
        state = conn.is_active()
        mac = conn.get_mac()
        itype = conn.get_type()
        ipv4 = conn.get_ipv4()
        ipv4_type = conn.get_ipv4_type()
        ipv6 = conn.get_ipv6()
        ipv6_type = conn.get_ipv6_type()
        bridge = conn.get_bridge()
        slave_ifaces = conn.get_bridge_slave_ifaces()

        if request.method == "POST":
            if "stop" in request.POST:
                conn.stop_iface()
                return HttpResponseRedirect(request.get_full_path())
            if "start" in request.POST:
                conn.start_iface()
                return HttpResponseRedirect(request.get_full_path())
            if "delete" in request.POST:
                conn.delete_iface()
                return HttpResponseRedirect(reverse("interfaces", args=[compute_id]))
        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    return render(request, "interface.html", locals())
