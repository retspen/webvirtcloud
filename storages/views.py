from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect, HttpResponse
from django.utils.translation import ugettext_lazy as _
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from computes.models import Compute
from storages.forms import AddStgPool, AddImage, CloneImage
from vrtManager.storage import wvmStorage, wvmStorages
from libvirt import libvirtError
from django.contrib import messages
import json


@login_required
def storages(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmStorages(compute.hostname,
                           compute.login,
                           compute.password,
                           compute.type)
        storages = conn.get_storages_info()
        secrets = conn.get_secrets()

        if request.method == 'POST':
            if 'create' in request.POST:
                form = AddStgPool(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    if data['name'] in storages:
                        msg = _("Pool name already use")
                        error_messages.append(msg)
                    if data['stg_type'] == 'rbd':
                        if not data['secret']:
                            msg = _("You need create secret for pool")
                            error_messages.append(msg)
                        if not data['ceph_pool'] and not data['ceph_host'] and not data['ceph_user']:
                            msg = _("You need input all fields for creating ceph pool")
                            error_messages.append(msg)
                    if not error_messages:
                        if data['stg_type'] == 'rbd':
                            conn.create_storage_ceph(data['stg_type'], data['name'],
                                                     data['ceph_pool'], data['ceph_host'],
                                                     data['ceph_user'], data['secret'])
                        elif data['stg_type'] == 'netfs':
                            conn.create_storage_netfs(data['stg_type'], data['name'],
                                                      data['netfs_host'], data['source'],
                                                      data['source_format'], data['target'])
                        else:
                            conn.create_storage(data['stg_type'], data['name'], data['source'], data['target'])
                        return HttpResponseRedirect(reverse('storage', args=[compute_id, data['name']]))
                else:
                    for msg_err in form.errors.values():
                        error_messages.append(msg_err.as_text())
        conn.close()
    except libvirtError as lib_err:
        error_messages.append(lib_err)

    return render(request, 'storages.html', locals())


@login_required
def storage(request, compute_id, pool):
    """
    :param request:
    :param compute_id:
    :param pool:
    :return:
    """

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    def handle_uploaded_file(path, f_name):
        target = path + '/' + str(f_name)
        destination = open(target, 'wb+')
        for chunk in f_name.chunks():
            destination.write(chunk)
        destination.close()

    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)
    meta_prealloc = False

    try:
        conn = wvmStorage(compute.hostname,
                          compute.login,
                          compute.password,
                          compute.type,
                          pool)

        storages = conn.get_storages()
        state = conn.is_active()
        size, free = conn.get_size()
        used = (size - free)
        if state:
            percent = (used * 100) / size
        else:
            percent = 0
        status = conn.get_status()
        path = conn.get_target_path()
        type = conn.get_type()
        autostart = conn.get_autostart()

        if state:
            conn.refresh()
            volumes = conn.update_volumes()
        else:
            volumes = None
    except libvirtError as lib_err:
        error_messages.append(lib_err)

    if request.method == 'POST':
        if 'start' in request.POST:
            try:
                conn.start()
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err.message)
        if 'stop' in request.POST:
            try:
                conn.stop()
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err.message)
        if 'delete' in request.POST:
            try:
                conn.delete()
                return HttpResponseRedirect(reverse('storages', args=[compute_id]))
            except libvirtError as lib_err:
                error_messages.append(lib_err.message)
        if 'set_autostart' in request.POST:
            try:
                conn.set_autostart(1)
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err.message)
        if 'unset_autostart' in request.POST:
            try:
                conn.set_autostart(0)
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err.message)
        if 'add_volume' in request.POST:
            form = AddImage(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                if data['meta_prealloc'] and data['format'] == 'qcow2':
                    meta_prealloc = True
                try:
                    name = conn.create_volume(data['name'], data['size'], data['format'], meta_prealloc)
                    messages.success(request, _("Image file {} is created successfully".format(name)))
                    return HttpResponseRedirect(request.get_full_path())
                except libvirtError as lib_err:
                    error_messages.append(lib_err)
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
        if 'del_volume' in request.POST:
            volname = request.POST.get('volname', '')
            try:
                vol = conn.get_volume(volname)
                vol.delete(0)
                messages.success(request, _('Volume: {} is deleted.'.format(volname)))
                return HttpResponseRedirect(request.get_full_path())
            except libvirtError as lib_err:
                error_messages.append(lib_err.message)
        if 'iso_upload' in request.POST:
            if str(request.FILES['file']) in conn.update_volumes():
                error_msg = _("ISO image already exist")
                error_messages.append(error_msg)
            else:
                handle_uploaded_file(path, request.FILES['file'])
                messages.success(request, _('ISO: {} is uploaded.'.format(request.FILES['file'])))
                return HttpResponseRedirect(request.get_full_path())
        if 'cln_volume' in request.POST:
            form = CloneImage(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                img_name = data['name']
                meta_prealloc = 0
                if img_name in conn.update_volumes():
                    msg = _("Name of volume already in use")
                    error_messages.append(msg)
                if not error_messages:
                    if data['convert']:
                        format = data['format']
                        if data['meta_prealloc'] and data['format'] == 'qcow2':
                            meta_prealloc = True
                    else:
                        format = None
                    try:
                        name = conn.clone_volume(data['image'], data['name'], format, meta_prealloc)
                        messages.success(request, _("{} image cloned as {} successfully".format(data['image'], name)))
                        return HttpResponseRedirect(request.get_full_path())
                    except libvirtError as lib_err:
                        error_messages.append(lib_err)
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())

    conn.close()

    return render(request, 'storage.html', locals())


@login_required
def get_volumes(request, compute_id, pool):
    data = {}
    compute = get_object_or_404(Compute, pk=compute_id)
    try:
        conn = wvmStorage(compute.hostname,
                          compute.login,
                          compute.password,
                          compute.type,
                          pool)
        conn.refresh()
    except libvirtError:
        pass
    data['vols'] = sorted(conn.get_volumes())
    return HttpResponse(json.dumps(data))
