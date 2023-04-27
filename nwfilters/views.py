from admin.decorators import superuser_only
from computes.models import Compute
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
# from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop as _
from libvirt import libvirtError
from logs.views import addlogmsg
from vrtManager import util
from vrtManager.instance import wvmInstance, wvmInstances
from vrtManager.nwfilters import wvmNWFilter, wvmNWFilters


@superuser_only
def nwfilters(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    nwfilters_all = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmNWFilters(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type
        )

        for nwf in conn.get_nwfilters():
            nwfilters_all.append(conn.get_nwfilter_info(nwf))

        if request.method == "POST":
            if "create_nwfilter" in request.POST:
                xml = request.POST.get("nwfilter_xml", "")
                if xml:
                    try:
                        util.etree.fromstring(xml)
                        name = util.get_xml_path(xml, "/filter/@name")
                        uuid = util.get_xml_path(xml, "/filter/uuid")
                    except util.etree.ParseError:
                        name = None

                    for nwf in nwfilters_all:
                        if name == nwf["name"]:
                            error_msg = _(
                                "A network filter with this name already exists"
                            )
                            raise Exception(error_msg)
                        if uuid == nwf["uuid"]:
                            error_msg = _(
                                "A network filter with this UUID already exists"
                            )
                            raise Exception(error_msg)
                    else:
                        try:
                            msg = _("%(filter)s network filter is created") % {
                                "filter": name
                            }
                            conn.create_nwfilter(xml)
                            addlogmsg(request.user.username, compute.hostname, "", msg, ip=get_client_ip(request))
                        except libvirtError as lib_err:
                            messages.error(request, lib_err)
                            addlogmsg(
                                request.user.username, compute.hostname, "", lib_err, ip=get_client_ip(request)
                            )

            if "del_nwfilter" in request.POST:
                name = request.POST.get("nwfiltername", "")
                msg = _("%(filter)s network filter is deleted") % {"filter": name}
                in_use = False
                nwfilter = conn.get_nwfilter(name)
                nwfilter_info = conn.get_nwfilter_info(name)

                is_conn = wvmInstances(
                    compute.hostname,
                    compute.login,
                    compute.password,
                    compute.type
                )
                instances = is_conn.get_instances()
                for inst in instances:
                    i_conn = wvmInstance(
                        compute.hostname,
                        compute.login,
                        compute.password,
                        compute.type,
                        inst,
                    )
                    dom_filterrefs = i_conn.get_filterrefs()

                    if name in dom_filterrefs:
                        in_use = True
                        msg = _(
                            "NWFilter is in use by %(instance)s. Cannot be deleted."
                        ) % {"instance": inst}
                        messages.error(request, msg)
                        addlogmsg(request.user.username, compute.hostname, "", msg, ip=get_client_ip(request))
                        i_conn.close()
                        break

                is_conn.close()
                if nwfilter and not in_use:
                    nwfilter.undefine()
                    nwfilters_all.remove(nwfilter_info)
                    addlogmsg(request.user.username, compute.hostname, "", msg, ip=get_client_ip(request))

            if "cln_nwfilter" in request.POST:
                name = request.POST.get("nwfiltername", "")
                cln_name = request.POST.get("cln_name", name + "-clone")

                conn.clone_nwfilter(name, cln_name)
                nwfilters_all.append(conn.get_nwfilter_info(cln_name))

                msg = _("Cloning NWFilter %(name)s as %(clone)s") % {
                    "name": name,
                    "clone": cln_name,
                }
                addlogmsg(request.user.username, compute.hostname, "", msg, ip=get_client_ip(request))

        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)
        addlogmsg(request.user.username, compute.hostname, "", lib_err, ip=get_client_ip(request))
    except Exception as err:
        messages.error(request, err)
        addlogmsg(request.user.username, compute.hostname, "", err, ip=get_client_ip(request))

    return render(
        request,
        "nwfilters.html",
        {
            "nwfilters": nwfilters_all,
            "compute": compute,
        },
    )


def nwfilter(request, compute_id, nwfltr):
    """
    :param request:
    :param compute_id:
    :param nwfltr:
    :return:
    """
    nwfilters_all = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        nwfilter = wvmNWFilter(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type,
            nwfltr
        )
        conn = wvmNWFilters(
            compute.hostname,
            compute.login,
            compute.password,
            compute.type
        )

        for nwf in conn.get_nwfilters():
            nwfilters_all.append(conn.get_nwfilter_info(nwf))

        uuid = nwfilter.get_uuid()
        name = nwfilter.get_name()
        xml = nwfilter.get_xml()
        rules = nwfilter.get_rules()
        refs = nwfilter.get_filter_refs()

        if request.method == "POST":

            if "edit_nwfilter" in request.POST:
                new_xml = request.POST.get("edit_xml", "")

                if new_xml:
                    nwfilter.delete()
                    try:
                        conn.create_nwfilter(new_xml)
                    except libvirtError as lib_err:
                        conn.create_nwfilter(xml)
                        raise libvirtError(lib_err)

            if "del_nwfilter_rule" in request.POST:
                action = request.POST.get("action", "")
                direction = request.POST.get("direction", "")
                priority = request.POST.get("priority", "")

                new_xml = nwfilter.delete_rule(action, direction, priority)
                nwfilter.delete()
                try:
                    conn.create_nwfilter(new_xml)
                except libvirtError as lib_err:
                    conn.create_nwfilter(xml)
                    raise libvirtError(lib_err)

            if "del_nwfilter_ref" in request.POST:
                ref_name = request.POST.get("ref")
                new_xml = nwfilter.delete_ref(ref_name)
                nwfilter.delete()
                try:
                    conn.create_nwfilter(new_xml)
                except libvirtError as lib_err:
                    conn.create_nwfilter(xml)
                    raise libvirtError(lib_err)

            if "add_nwfilter_rule" in request.POST:
                rule_xml = request.POST.get("nwfilterrule_xml", "")
                if not rule_xml:
                    return HttpResponseRedirect(request.get_full_path())
                new_xml = nwfilter.add_rule(rule_xml)
                nwfilter.delete()
                try:
                    conn.create_nwfilter(new_xml)
                except libvirtError as lib_err:
                    conn.create_nwfilter(xml)
                    raise libvirtError(lib_err)

            if "add_nwfilter_ref" in request.POST:
                ref_name = request.POST.get("nwfilters_select", "")
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
        messages.error(request, lib_err)
    except Exception as error_msg:
        messages.error(request, error_msg)

    return render(request, "nwfilter.html", locals())

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip