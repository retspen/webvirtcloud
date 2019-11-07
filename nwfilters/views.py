# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils.translation import ugettext_lazy as _
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from computes.models import Compute
from vrtManager import util
from vrtManager.nwfilters import wvmNWFilters, wvmNWFilter
from vrtManager.instance import wvmInstances, wvmInstance
from libvirt import libvirtError
from logs.views import addlogmsg


@login_required
def nwfilters(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    error_messages = []
    nwfilters_all = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmNWFilters(compute.hostname,
                            compute.login,
                            compute.password,
                            compute.type)

        if request.method == 'POST':
            if 'create_nwfilter' in request.POST:
                xml = request.POST.get('nwfilter_xml', '')
                if xml:
                    try:
                        util.etree.fromstring(xml)
                        name = util.get_xml_path(xml, '/filter/@name')
                        uuid = util.get_xml_path(xml, '/filter/uuid')
                    except util.etree.ParseError:
                        name = None

                    for nwf in nwfilters:
                        if name == nwf.name():
                            error_msg = _("A network filter with this name already exists")
                            raise Exception(error_msg)
                        if uuid == nwf.UUIDString():
                            error_msg = _("A network filter with this uuid already exists")
                            raise Exception(error_msg)
                    else:
                        try:
                            msg = _("Creating NWFilter: %s" % name)
                            conn.create_nwfilter(xml)
                            addlogmsg(request.user.username, compute.hostname, msg)
                        except libvirtError as lib_err:
                            error_messages.append(lib_err.message)
                            addlogmsg(request.user.username, compute.hostname, lib_err.message)

            if 'del_nwfilter' in request.POST:
                name = request.POST.get('nwfiltername', '')
                msg = _("Deleting NWFilter: %s" % name)
                in_use = False
                nwfilter = conn.get_nwfilter(name)

                is_conn = wvmInstances(compute.hostname, compute.login, compute.password, compute.type)
                instances = is_conn.get_instances()
                for inst in instances:
                    i_conn = wvmInstance(compute.hostname, compute.login, compute.password, compute.type, inst)
                    dom_filterrefs = i_conn.get_filterrefs()

                    if name in dom_filterrefs:
                        in_use = True
                        msg = _("NWFilter is in use by %s. Cannot be deleted." % inst)
                        error_messages.append(msg)
                        addlogmsg(request.user.username, compute.hostname, msg)
                        i_conn.close()
                        break

                is_conn.close()
                if nwfilter and not in_use:
                    nwfilter.undefine()
                    addlogmsg(request.user.username, compute.hostname, msg)

            if 'cln_nwfilter' in request.POST:

                name = request.POST.get('nwfiltername', '')
                cln_name = request.POST.get('cln_name', name + '-clone')

                conn.clone_nwfilter(name, cln_name)
                msg = _("Cloning NWFilter %s as %s" % (name, cln_name))
                addlogmsg(request.user.username, compute.hostname, msg)

        for nwf in conn.get_nwfilters():
            nwfilters_all.append(conn.get_nwfilter_info(nwf))

        conn.close()
    except libvirtError as lib_err:
        error_messages.append(lib_err)
        addlogmsg(request.user.username, compute.hostname, lib_err)
    except Exception as err:
        error_messages.append(err)
        addlogmsg(request.user.username, compute.hostname, err)

    return render(request, 'nwfilters.html', {'error_messages': error_messages,
                                              'nwfilters': nwfilters_all,
                                              'compute': compute})


@login_required
def nwfilter(request, compute_id, nwfltr):

    error_messages = []
    nwfilters_all = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        nwfilter = wvmNWFilter(compute.hostname,
                               compute.login,
                               compute.password,
                               compute.type,
                               nwfltr)
        conn = wvmNWFilters(compute.hostname,
                            compute.login,
                            compute.password,
                            compute.type)

        for nwf in conn.get_nwfilters():
            nwfilters_all.append(conn.get_nwfilter_info(nwf))

        uuid = nwfilter.get_uuid()
        name = nwfilter.get_name()
        xml = nwfilter.get_xml()
        rules = nwfilter.get_rules()
        refs = nwfilter.get_filter_refs()

        if request.method == 'POST':

            if 'edit_nwfilter' in request.POST:
                new_xml = request.POST.get('edit_xml', '')

                if new_xml:
                    nwfilter.delete()
                    try:
                        conn.create_nwfilter(new_xml)
                    except libvirtError as lib_err:
                        conn.create_nwfilter(xml)
                        raise libvirtError(lib_err)

            if 'del_nwfilter_rule' in request.POST:
                action = request.POST.get('action', '')
                direction = request.POST.get('direction', '')
                priority = request.POST.get('priority', '')

                new_xml = nwfilter.delete_rule(action, direction, priority)
                nwfilter.delete()
                try:
                    conn.create_nwfilter(new_xml)
                except libvirtError as lib_err:
                    conn.create_nwfilter(xml)
                    raise libvirtError(lib_err)

            if 'del_nwfilter_ref' in request.POST:
                ref_name = request.POST.get('ref')
                new_xml = nwfilter.delete_ref(ref_name)
                nwfilter.delete()
                try:
                    conn.create_nwfilter(new_xml)
                except libvirtError as lib_err:
                    conn.create_nwfilter(xml)
                    raise libvirtError(lib_err)

            if 'add_nwfilter_rule' in request.POST:
                rule_xml = request.POST.get('nwfilterrule_xml', '')
                if not rule_xml:
                    return HttpResponseRedirect(request.get_full_path())
                new_xml = nwfilter.add_rule(rule_xml)
                nwfilter.delete()
                try:
                    conn.create_nwfilter(new_xml)
                except libvirtError as lib_err:
                    conn.create_nwfilter(xml)
                    raise libvirtError(lib_err)

            if 'add_nwfilter_ref' in request.POST:
                ref_name = request.POST.get('nwfilters_select', '')
                if not ref_name:
                    return HttpResponseRedirect(request.get_full_path())
                new_xml = nwfilter.add_ref(ref_name)
                nwfilter.delete()
                try:
                    conn.create_nwfilter(new_xml)
                except libvirtError as lib_err:
                    conn.create_nwfilter(xml)
                    raise libvirtError(lib_err)

            return HttpResponseRedirect(request.get_full_path())
        conn.close()
        nwfilter.close()
    except libvirtError as lib_err:
        error_messages.append(lib_err)
    except Exception as error_msg:
        error_messages.append(error_msg)

    return render(request, 'nwfilter.html', locals())
