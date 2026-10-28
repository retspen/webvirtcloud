from admin.decorators import superuser_only
from computes.models import Compute
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


@superuser_only
def networks(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmNetworks(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        networks = conn.get_networks_info()

        if request.method == "POST" and "create" in request.POST:
            form = AddNetPool(request.POST, networks=networks)
            if form.is_valid():
                data = form.cleaned_data
                gateway4 = netmask4 = dhcp4 = gateway6 = prefix6 = dhcp6 = ""
                if data["subnet"]:
                    gateway4, netmask4, dhcp4 = network_size(data["subnet"], data["dhcp4"])
                if data["subnet6"]:
                    gateway6, prefix6, dhcp6 = network_size(data["subnet6"], data["dhcp6"])
                with audit(request, compute, f"Network {data['name']}", "add"):
                    conn.create_network(
                        data["name"], data["forward"],
                        bool(data["subnet"]), gateway4, netmask4, dhcp4,
                        bool(data["subnet6"]), gateway6, prefix6, dhcp6,
                        data["bridge_name"], data["openvswitch"],
                    )
                return HttpResponseRedirect(reverse("network", args=[compute_id, data["name"]]))
            if form.has_error("name", "taken"):
                failed(request, compute, f"Network {form.data['name'].strip()}", "add", "name already in use")
            for msg_err in form.errors.values():
                messages.error(request, msg_err.as_text())
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
        networks = conn.get_networks()
        state = conn.is_active()
        device = conn.get_bridge_device()
        autostart = conn.get_autostart()
        net_mac = conn.get_network_mac()
        net_forward = conn.get_network_forward()
        qos = conn.get_qos()
        ip_networks = conn.get_ip_networks()
        # the page shows the first address of each family
        ipv4 = next((ip for ip in ip_networks if ip["family"] == "ipv4"), None)
        ipv6 = next((ip for ip in ip_networks if ip["family"] == "ipv6"), None)
        xml = conn.config_xml()
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
    conn.close()

    return render(request, "network.html", locals())
