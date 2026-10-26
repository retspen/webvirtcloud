from django.contrib import messages
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError
from computes.models import Compute
from interfaces.forms import AddInterface
from logs.audit import audit
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
        conn = wvmInterfaces(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type
        )
        ifaces = conn.get_ifaces()
        changeable = conn.can_change_interfaces()

        # the host's devices are only the create form's choices
        netdevs, netdev_error = [], None
        if changeable:
            try:
                netdevs = conn.get_net_devices()
            except Exception as err:
                netdev_error = err
                messages.error(request, _("The network devices of this host could not be read: %(error)s") % {"error": err})

        for iface in ifaces:
            interf = wvmInterface(
                compute.hostname,
                compute.login,
                compute.password,
                compute.type,
                iface
            )
            ifaces_all.append(interf.get_details())

        if request.method == "POST":
            # the page says why nothing is created on a host that cannot change
            # interfaces; without the host's devices nothing can be checked
            if "create" in request.POST and changeable and netdev_error is None:
                form = AddInterface(request.POST, netdevs=netdevs, defined=ifaces)
                if form.is_valid():
                    data = form.cleaned_data
                    with audit(request, compute, f"Interface {data['name']}", "add"):
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
        conn = wvmInterface(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
            iface
        )
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
        changeable = conn.can_change_interfaces()

        # the page says why nothing is done on a host that cannot change interfaces
        if request.method == "POST" and changeable:
            if "stop" in request.POST:
                with audit(request, compute, f"Interface {iface}", "stop"):
                    conn.stop_iface()
                return HttpResponseRedirect(request.get_full_path())
            if "start" in request.POST:
                with audit(request, compute, f"Interface {iface}", "start"):
                    conn.start_iface()
                return HttpResponseRedirect(request.get_full_path())
            if "delete" in request.POST:
                with audit(request, compute, f"Interface {iface}", "delete"):
                    conn.delete_iface()
                return HttpResponseRedirect(reverse("interfaces", args=[compute_id]))
        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    return render(request, "interface.html", locals())
