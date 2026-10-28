from admin.decorators import superuser_only
from computes.models import Compute
from instances.models import Instance
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError
from logs.audit import audit, failed
from vrtManager.network import network_size, wvmNetwork, wvmNetworks
from vrtManager.util import OperationError

from networks.forms import AddNetPool


# a network's mode (vrtManager.network.network_mode): its name, and what it does
MODES = {
    "isolated": (_("Isolated"), _("VMs reach each other and the host only.")),
    "nat": (_("NAT"), _("VMs reach out through the host's address; IPv6, when set, is routed.")),
    "route": (_("Routed"), _("The host routes the subnet; the upstream router needs a route back to it.")),
    "open": (_("Open"), _("The host routes the subnet and adds no firewall rules for it.")),
    "bridge": (_("Bridge"), _("VMs join a bridge of the host and take their addresses from its network.")),
    "macvtap": (_("Macvtap"), _("VMs share an interface of the host; the host cannot reach them through it.")),
    "hostdev": (_("SR-IOV"), _("VMs get a virtual function of the host's network card.")),
}
# the modes libvirt gives no addresses of its own: the outside network does
EXTERNAL = ("bridge", "macvtap", "hostdev")


@superuser_only
def networks(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    compute = get_object_or_404(Compute, pk=compute_id)
    form = AddNetPool()
    # the new network dialog's mode: the one sent back after a refusal
    net_mode = request.POST.get("forward", "nat")

    try:
        conn = wvmNetworks(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        networks = conn.get_networks_info()
        for net in networks:
            net["mode_label"] = MODES.get(net["mode"], (net["mode"], ""))[0]
            net["external"] = net["mode"] in EXTERNAL
        # suggestions for a bridge or macvtap network: not the bridges libvirt made for its own networks
        taken = {net["device"] for net in networks if not net["external"]}
        host_ifaces = [iface for iface in conn.get_host_interfaces() if iface["name"] not in taken]

        if request.method == "POST" and "create" in request.POST:
            form = AddNetPool(request.POST, networks=networks)
            if form.is_valid():
                data = form.cleaned_data
                gateway4 = netmask4 = dhcp4 = gateway6 = prefix6 = dhcp6 = ""
                if data["subnet"]:
                    gateway4, netmask4, dhcp4 = network_size(data["subnet"], data["dhcp4"])
                if data["subnet6"]:
                    gateway6, prefix6, dhcp6 = network_size(data["subnet6"], data["dhcp6"])
                try:
                    with audit(request, compute, f"Network {data['name']}", "add"):
                        conn.create_network(
                            data["name"], data["forward"],
                            bool(data["subnet"]), gateway4, netmask4, dhcp4,
                            bool(data["subnet6"]), gateway6, prefix6, dhcp6,
                            data["bridge_name"], data["openvswitch"],
                        )
                except libvirtError as err:  # shown in the dialog, which opens again
                    form.add_error(None, str(err))
                else:
                    return HttpResponseRedirect(reverse("network", args=[compute_id, data["name"]]))
            elif form.has_error("name", "taken"):
                failed(request, compute, f"Network {form.data['name'].strip()}", "add", "name already in use")
        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    return render(request, "networks.html", locals())


@superuser_only
def network(request, compute_id, pool):
    """
    :param request:
    :param compute_id:
    :param pool:
    :return:
    """

    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmNetwork(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
            pool,
        )
    except libvirtError as lib_err:
        messages.error(request, lib_err)
        return HttpResponseRedirect(reverse("networks", args=[compute_id]))

    if request.method == "POST":
        subject = f"Network {pool}"
        here = reverse("network", args=[compute_id, pool])
        if "start" in request.POST:
            try:
                with audit(request, compute, subject, "start"):
                    conn.start()
                return HttpResponseRedirect(here)
            except libvirtError as lib_err:
                messages.error(request, lib_err)
        if "stop" in request.POST:
            try:
                with audit(request, compute, subject, "stop"):
                    conn.stop()
                return HttpResponseRedirect(here)
            except libvirtError as lib_err:
                messages.error(request, lib_err)
        if "delete" in request.POST:
            try:
                with audit(request, compute, subject, "delete"):
                    conn.delete()
                return HttpResponseRedirect(reverse("networks", args=[compute_id]))
            except libvirtError as lib_err:
                messages.error(request, lib_err)
        if "set_autostart" in request.POST:
            try:
                with audit(request, compute, subject, "autostart on"):
                    conn.set_autostart(1)
                return HttpResponseRedirect(here)
            except libvirtError as lib_err:
                messages.error(request, lib_err)
        if "unset_autostart" in request.POST:
            try:
                with audit(request, compute, subject, "autostart off"):
                    conn.set_autostart(0)
                return HttpResponseRedirect(here)
            except libvirtError as lib_err:
                messages.error(request, lib_err)
        # an address of the network by its index (ip_networks), an entry by the address it had
        try:
            ip_index = int(request.POST.get("ip_index", ""))
        except ValueError:
            ip_index = -1
        if "modify_fixed_address" in request.POST:
            address = request.POST.get("address", "")
            mac_duid = request.POST.get("mac") or request.POST.get("id", "")
            try:
                with audit(request, compute, subject, f"set fixed address {address}") as entry:
                    changed = conn.modify_fixed_address(ip_index, request.POST.get("original", ""),
                                                        request.POST.get("name", ""), address, mac_duid)
                    entry.skip = changed is False  # nothing was done
                if changed is False:
                    messages.info(request, _("The fixed address is unchanged"))
                else:
                    messages.success(request, _("The fixed address %(address)s is set") % {"address": address})
            except (libvirtError, OperationError) as err:
                messages.error(request, err)
            return HttpResponseRedirect(here)
        if "delete_fixed_address" in request.POST:
            address = request.POST.get("original", "")
            try:
                with audit(request, compute, subject, f"delete fixed address {address}"):
                    conn.delete_fixed_address(ip_index, address)
                messages.success(request, _("The fixed address %(address)s is deleted") % {"address": address})
            except (libvirtError, OperationError) as err:
                messages.error(request, err)
            return HttpResponseRedirect(here)
        if "modify_dhcp_range" in request.POST:
            try:
                with audit(request, compute, subject, "set DHCP range"):
                    conn.modify_dhcp_range(ip_index, request.POST.get("range_start", ""), request.POST.get("range_end", ""))
                messages.success(request, _("The DHCP range is changed"))
            except (libvirtError, OperationError) as err:
                messages.error(request, err)
            return HttpResponseRedirect(here)
        if "edit_network" in request.POST:
            edit_xml = request.POST.get("edit_xml", "")
            if edit_xml:
                try:
                    with audit(request, compute, subject, "change XML"):
                        conn.edit_network(edit_xml)
                except (libvirtError, OperationError) as err:
                    messages.error(request, err)
                    return HttpResponseRedirect(here)
                if conn.is_active():
                    messages.success(
                        request,
                        _(
                            "Network XML is changed. "
                            "Stop and start network to activate new config."
                        ),
                    )
                else:
                    messages.success(request, _("Network XML is changed."))
                return HttpResponseRedirect(here)
        if "set_qos" in request.POST:
            qos_dir = request.POST.get("qos_direction", "")
            average = request.POST.get("qos_average") or 0
            peak = request.POST.get("qos_peak") or 0
            burst = request.POST.get("qos_burst") or 0

            try:
                with audit(request, compute, subject, f"set QoS {qos_dir}"):
                    conn.set_qos(qos_dir, average, peak, burst)
                if conn.is_active():
                    messages.success(
                        request,
                        _(
                            "%(qos_dir)s QoS is updated. Network XML is changed. Stop and start network to activate new config"
                        )
                        % {"qos_dir": qos_dir.capitalize()},
                    )
                else:
                    messages.success(
                        request,
                        _("%(qos_dir)s QoS is set") % {"qos_dir": qos_dir.capitalize()},
                    )
            except (libvirtError, ValueError) as err:
                messages.error(request, err)
            return HttpResponseRedirect(here)
        if "unset_qos" in request.POST:
            qos_dir = request.POST.get("qos_direction", "")
            try:
                with audit(request, compute, subject, f"unset QoS {qos_dir}"):
                    conn.unset_qos(qos_dir)
            except (libvirtError, ValueError) as err:
                messages.error(request, err)
                return HttpResponseRedirect(here)

            if conn.is_active():
                messages.success(
                    request,
                    _(
                        "%(qos_dir)s QoS is deleted. Network XML is changed. "
                        "Stop and start network to activate new config"
                    )
                    % {"qos_dir": qos_dir.capitalize()},
                )
            else:
                messages.success(
                    request,
                    _("%(qos_dir)s QoS is deleted") % {"qos_dir": qos_dir.capitalize()},
                )
            return HttpResponseRedirect(here)
    # read only for the page: every action above redirects
    try:
        state = conn.is_active()
        device = conn.get_bridge_device()
        autostart = conn.get_autostart()
        net_mac = conn.get_network_mac()
        qos = conn.get_qos()
        ip_networks = conn.get_ip_networks()
        mode = conn.get_mode()
        mode_label, mode_help = MODES.get(mode, (mode, ""))
        external = mode in EXTERNAL
        # libvirt limits the bandwidth of routed, isolated and host bridge networks, not of macvtap or SR-IOV ones
        qos_supported = mode in ("isolated", "nat", "route", "open", "bridge")
        families = {ip["family"] for ip in ip_networks}
        # every fixed address, with the address of the network it belongs to
        fixed_addresses = [{**host, "ip_index": ip["index"], "subnet": ip["subnet"]}
                           for ip in ip_networks for host in ip["hosts"]]
        dhcp_networks = [ip for ip in ip_networks if ip["dhcp"]]
        vms = conn.get_vms()
        vm_ids = dict(Instance.objects.filter(compute=compute, name__in=[vm["name"] for vm in vms]).values_list("name", "id"))
        for vm in vms:
            vm["id"] = vm_ids.get(vm["name"])
        xml = conn.saved_xml
    except libvirtError as lib_err:
        messages.error(request, lib_err)
        return HttpResponseRedirect(reverse("networks", args=[compute_id]))
    conn.close()

    return render(request, "network.html", locals())
