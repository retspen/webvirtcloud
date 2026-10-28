from admin.decorators import superuser_only
from computes.models import Compute
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from instances.models import Instance
from libvirt import libvirtError
from logs.audit import audit
from vrtManager import util
from vrtManager.nwfilters import wvmNWFilter, wvmNWFilters


@superuser_only
def nwfilters(request, compute_id):
    """The host's network filters; one created, cloned or deleted, after
    which the list is read again."""
    compute = get_object_or_404(Compute, pk=compute_id)
    nwfilters_all = []

    try:
        conn = wvmNWFilters(compute.hostname, compute.login, compute.password, compute.type)

        if request.method == "POST":
            name = request.POST.get("nwfiltername", "")
            if "create_nwfilter" in request.POST:
                xml = request.POST.get("nwfilter_xml", "")
                try:  # the row names the filter where the XML does
                    new_name = util.parse_xml(xml).get("name")
                except util.OperationError:
                    new_name = None
                with audit(request, compute, f"Network filter {new_name or '(no name)'}", "add"):
                    conn.create_nwfilter(xml)
            elif "cln_nwfilter" in request.POST:
                clone_name = request.POST.get("cln_name", "")
                with audit(request, compute, f"Network filter {name}", f"clone as {clone_name}"):
                    conn.clone_nwfilter(name, clone_name)
            elif "del_nwfilter" in request.POST:
                with audit(request, compute, f"Network filter {name}", "delete"):
                    conn.delete_nwfilter(name)
            return HttpResponseRedirect(request.get_full_path())

        # the VMs first: a list without them would offer to delete filters in use
        users = conn.get_users()
        nwfilters_all = conn.get_nwfilters_info()
        for nwf in nwfilters_all:
            nwf["vms"] = users.get(nwf["name"], [])
    except libvirtError as lib_err:  # OperationError too: a name in use, a filter in use
        messages.error(request, lib_err)
        if request.method == "POST":  # a host not reached as well: nothing was changed
            return HttpResponseRedirect(request.get_full_path())

    return render(request, "nwfilters.html", {"nwfilters": nwfilters_all, "compute": compute})


@superuser_only
def nwfilter(request, compute_id, nwfltr):
    """A network filter of the host: its rules and references changed one at
    a time, or its XML as a whole."""
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        nwfilter = wvmNWFilter(compute.hostname, compute.login, compute.password, compute.type, nwfltr)

        if request.method == "POST":
            post = request.POST
            subject = f"Network filter {nwfltr}"
            try:
                if "edit_nwfilter" in post:
                    with audit(request, compute, subject, "change XML"):
                        nwfilter.edit(post.get("edit_xml", ""))
                elif "add_nwfilter_rule" in post:
                    with audit(request, compute, subject, "add rule"):
                        nwfilter.add_rule(post.get("nwfilterrule_xml", ""))
                elif "del_nwfilter_rule" in post:
                    with audit(request, compute, subject, "delete rule"):
                        nwfilter.delete_rule(post.get("index", ""), post.get("rule", ""))
                elif "add_nwfilter_ref" in post:
                    ref_name = post.get("nwfilters_select", "")
                    with audit(request, compute, subject, f"add reference {ref_name}"):
                        nwfilter.add_ref(ref_name)
                elif "del_nwfilter_ref" in post:
                    with audit(request, compute, subject, "delete reference") as entry:
                        entry.action = f"delete reference {nwfilter.delete_ref(post.get('index', ''), post.get('ref', ''))}"
            except libvirtError as err:  # OperationError too: a filter changed meanwhile, XML refused
                messages.error(request, err)
            return HttpResponseRedirect(request.get_full_path())

        name = nwfilter.get_name()
        uuid = nwfilter.get_uuid()
        xml = nwfilter.get_xml()
        chain = nwfilter.tree.get("chain")
        priority = nwfilter.tree.get("priority")
        rules = nwfilter.get_rules()
        refs = nwfilter.get_refs()
        ref_choices = nwfilter.get_ref_choices()
        filter_names = nwfilter.get_nwfilters()
        referenced_by = [nwf["name"] for nwf in nwfilter.get_nwfilters_info() if name in nwf["refs"]]
        vm_names = nwfilter.get_users().get(name, [])
        vm_ids = dict(Instance.objects.filter(compute=compute, name__in=vm_names).values_list("name", "id"))
        vms = [{"name": vm_name, "id": vm_ids.get(vm_name)} for vm_name in vm_names]
    except libvirtError as lib_err:
        messages.error(request, lib_err)
        if request.method == "POST":  # a filter gone meanwhile, a host not reached: nothing was changed
            return HttpResponseRedirect(reverse("nwfilters", args=[compute_id]))

    return render(request, "nwfilter.html", locals())
