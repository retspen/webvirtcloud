from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from libvirt import libvirtError

from admin.decorators import superuser_only
from computes.models import Compute
from networks.forms import AddNetPool
from vrtManager.network import network_size, wvmNetwork, wvmNetworks


@superuser_only
def networks(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmNetworks(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
        )
        networks = conn.get_networks_info()
        dhcp4 = netmask4 = gateway4 = ''
        dhcp6 = prefix6 = gateway6 = ''
        ipv4 = ipv6 = False

        if request.method == 'POST':
            if 'create' in request.POST:
                form = AddNetPool(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    if data['name'] in networks:
                        msg = _("Network pool name already in use")
                        error_messages.append(msg)
                    if data['forward'] in ['bridge', 'macvtap'] and data['bridge_name'] == '':
                        error_messages.append(_('Please enter bridge/dev name'))
                    if data['subnet']:
                        ipv4 = True
                        gateway4, netmask4, dhcp4 = network_size(data['subnet'], data['dhcp4'])
                    if data['subnet6']:
                        ipv6 = True
                        gateway6, prefix6, dhcp6 = network_size(data['subnet6'], data['dhcp6'])
                        if prefix6 != '64':
                            error_messages.append(_('For libvirt, the IPv6 network prefix must be /64'))
                    if not error_messages:
                        conn.create_network(
                            data['name'],
                            data['forward'],
                            ipv4,
                            gateway4,
                            netmask4,
                            dhcp4,
                            ipv6,
                            gateway6,
                            prefix6,
                            dhcp6,
                            data['bridge_name'],
                            data['openvswitch'],
                            data['fixed'],
                        )
                        return HttpResponseRedirect(reverse('network', args=[compute_id, data['name']]))
                else:
                    for msg_err in form.errors.values():
                        error_messages.append(msg_err.as_text())
        conn.close()
    except libvirtError as lib_err:
        error_messages.append(lib_err)

    return render(request, 'networks.html', locals())


@superuser_only
def network(request, compute_id, pool):
    """
    :param request:
    :param compute_id:
    :param pool:
    :return:
    """

    error_messages = []
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
        dhcp_range_start = ipv4_dhcp_range_end = dict()

        ip_networks = conn.get_ip_networks()
        for family, ip_network in ip_networks.items():
            if family == "ipv4":
                ipv4_dhcp_range_start = conn.get_dhcp_range_start(family)
                ipv4_dhcp_range_end = conn.get_dhcp_range_end(family)
                ipv4_network = ip_network
                ipv4_fixed_address = conn.get_dhcp_host_addr(family)
            elif family == "ipv6":
                ipv6_dhcp_range_start = conn.get_dhcp_range_start(family)
                ipv6_dhcp_range_end = conn.get_dhcp_range_end(family)
                ipv6_network = ip_network
                ipv6_fixed_address = conn.get_dhcp_host_addr(family)
            else:
                raise Exception(_("Unknown Network Family"))

        xml = conn._XMLDesc(0)
    except libvirtError as lib_err:
        error_messages.append(lib_err)
        return HttpResponseRedirect(reverse('networks', args=compute_id))

    if request.method == 'POST':
        if 'start' in request.POST:
            try:
                conn.start()
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err)
        if 'stop' in request.POST:
            try:
                conn.stop()
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err)
        if 'delete' in request.POST:
            try:
                conn.delete()
                return HttpResponseRedirect(reverse('networks', args=[compute_id]))
            except libvirtError as lib_err:
                error_messages.append(lib_err)
        if 'set_autostart' in request.POST:
            try:
                conn.set_autostart(1)
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err)
        if 'unset_autostart' in request.POST:
            try:
                conn.set_autostart(0)
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err)
        if 'modify_fixed_address' in request.POST:
            name = request.POST.get('name', '')
            address = request.POST.get('address', '')
            family = request.POST.get('family', 'ipv4')

            if family == 'ipv4':
                mac_duid = request.POST.get('mac', '')
            if family == 'ipv6':
                mac_duid = request.POST.get('id', '')

            try:
                ret_val = conn.modify_fixed_address(name, address, mac_duid, family)
                messages.success(request, _(f"{family.upper()} Fixed Address Operation Completed."))
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err)
            except ValueError as val_err:
                error_messages.append(val_err)
        if 'delete_fixed_address' in request.POST:
            ip = request.POST.get('address', '')
            family = request.POST.get('family', 'ipv4')
            conn.delete_fixed_address(ip, family)
            messages.success(request, _(f"{family.upper()} Fixed Address is Deleted."))
            return HttpResponseRedirect(request.get_full_path())
        if 'modify_dhcp_range' in request.POST:
            range_start = request.POST.get('range_start', '')
            range_end = request.POST.get('range_end', '')
            family = request.POST.get('family', 'ipv4')
            try:
                conn.modify_dhcp_range(range_start, range_end, family)
                messages.success(request, _(f"{family.upper()} DHCP Range is Changed."))
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err)
        if 'edit_network' in request.POST:
            edit_xml = request.POST.get('edit_xml', '')
            if edit_xml:
                conn.edit_network(edit_xml)
                if conn.is_active():
                    messages.success(request, _("Network XML is changed. \\" "Stop and start network to activate new config."))
                else:
                    messages.success(request, _("Network XML is changed."))
                return HttpResponseRedirect(request.get_full_path())
        if 'set_qos' in request.POST:
            qos_dir = request.POST.get('qos_direction', '')
            average = request.POST.get('qos_average') or 0
            peak = request.POST.get('qos_peak') or 0
            burst = request.POST.get('qos_burst') or 0

            try:
                conn.set_qos(qos_dir, average, peak, burst)
                if conn.is_active():
                    messages.success(
                        request, 
                        _(f"{qos_dir.capitalize()} QoS is set. Network XML is changed.") +
                        _("Stop and start network to activate new config"))
                else:
                    messages.success(request, _("{} QoS is set").format(qos_dir.capitalize()))
            except libvirtError as lib_err:
                messages.error(request, lib_err)
            return HttpResponseRedirect(request.get_full_path())
        if 'unset_qos' in request.POST:
            qos_dir = request.POST.get('qos_direction', '')
            conn.unset_qos(qos_dir)

            if conn.is_active():
                messages.success(
                    request, 
                    _(f"{qos_dir.capitalize()} QoS is deleted. Network XML is changed. ") +
                    _("Stop and start network to activate new config."))
            else:
                messages.success(request, _(f"{qos_dir.capitalize()} QoS is deleted"))
            return HttpResponseRedirect(request.get_full_path())
    conn.close()

    return render(request, 'network.html', locals())
