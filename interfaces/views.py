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
    """The host's interfaces, and a new one where its libvirt can define them."""
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmInterfaces(compute.hostname, compute.login, compute.password, compute.type)
        ifaces_all = conn.get_ifaces_info()
        changeable = conn.can_change_interfaces()

        # the host's devices are only the create form's choices
        netdevs, members, netdev_error = [], [], None
        if changeable:
            try:
                netdevs = conn.get_net_devices()
                members = conn.get_member_candidates(netdevs)
            except Exception as err:  # a host without the node device driver too
                netdev_error = err
                messages.error(request, _("The network devices of this host could not be read: %(error)s") % {"error": err})

        # the page says why nothing is created on a host that cannot change
        # interfaces; without the host's devices nothing can be checked
        if request.method == "POST" and "create" in request.POST and changeable and netdev_error is None:
            form = AddInterface(request.POST, netdevs=netdevs, members=members,
                                defined=[iface["name"] for iface in ifaces_all])
            if form.is_valid():
                data = form.cleaned_data
                with audit(request, compute, f"Interface {data['name']}", "add"):
                    conn.create_iface(
                        data["name"], data["itype"], data["start_mode"], data["netdev"],
                        data["ipv4_type"], data["ipv4_addr"], data["ipv4_gw"],
                        data["ipv6_type"], data["ipv6_addr"], data["ipv6_gw"],
                        data["stp"], data["delay"],
                    )
                return HttpResponseRedirect(reverse("interfaces", args=[compute_id]))
            for msg_err in form.errors.values():
                messages.error(request, msg_err.as_text())
        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    return render(request, "interfaces.html", locals())


@superuser_only
def interface(request, compute_id, iface):
    """An interface of the host; started, stopped or deleted where the host's libvirt can."""
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmInterface(compute.hostname, compute.login, compute.password, compute.type, iface)
        changeable = conn.can_change_interfaces()

        # the page says why nothing is done on a host that cannot change interfaces
        if request.method == "POST" and changeable:
            here = reverse("interface", args=[compute_id, iface])
            subject = f"Interface {iface}"
            try:
                if "stop" in request.POST:
                    with audit(request, compute, subject, "stop"):
                        conn.stop_iface()
                    return HttpResponseRedirect(here)
                if "start" in request.POST:
                    with audit(request, compute, subject, "start"):
                        conn.start_iface()
                    return HttpResponseRedirect(here)
                if "delete" in request.POST:
                    with audit(request, compute, subject, "delete"):
                        conn.delete_iface()
                    return HttpResponseRedirect(reverse("interfaces", args=[compute_id]))
            except libvirtError as err:  # OperationError too: an active one, a bridge whose addresses go nowhere
                messages.error(request, err)
                return HttpResponseRedirect(here)

        info = conn.get_info()
        state = conn.is_active()
        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    return render(request, "interface.html", locals())
