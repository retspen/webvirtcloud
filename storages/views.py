import json

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from libvirt import libvirtError

from admin.decorators import superuser_only
from appsettings.models import AppSettings
from appsettings.settings import app_settings
from computes.models import Compute
from storages.forms import AddStgPool, CloneImage, CreateVolumeForm
from vrtManager.storage import wvmStorage, wvmStorages


@superuser_only
def storages(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmStorages(compute.hostname, compute.login, compute.password, compute.type)
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
                            conn.create_storage_ceph(data['stg_type'], data['name'], data['ceph_pool'], data['ceph_host'],
                                                     data['ceph_user'], data['secret'])
                        elif data['stg_type'] == 'netfs':
                            conn.create_storage_netfs(data['stg_type'], data['name'], data['netfs_host'], data['source'],
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


@superuser_only
def storage(request, compute_id, pool):
    """
    :param request:
    :param compute_id:
    :param pool:
    :return:
    """
    def handle_uploaded_file(path, f_name):
        target = path + '/' + str(f_name)
        destination = open(target, 'wb+')
        for chunk in f_name.chunks():
            destination.write(chunk)
        destination.close()

    compute = get_object_or_404(Compute, pk=compute_id)
    meta_prealloc = False
    form = CreateVolumeForm()

    conn = wvmStorage(compute.hostname, compute.login, compute.password, compute.type, pool)

    storages = conn.get_storages()
    state = conn.is_active()
    size, free = conn.get_size()
    used = (size - free)
    if state:
        percent = (used * 100) // size
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

    if request.method == 'POST':
        if 'start' in request.POST:
            conn.start()
            return HttpResponseRedirect(request.get_full_path())
        if 'stop' in request.POST:
            conn.stop()
            return HttpResponseRedirect(request.get_full_path())
        if 'delete' in request.POST:
            conn.delete()
            return HttpResponseRedirect(reverse('storages', args=[compute_id]))
        if 'set_autostart' in request.POST:
            conn.set_autostart(1)
            return HttpResponseRedirect(request.get_full_path())
        if 'unset_autostart' in request.POST:
            conn.set_autostart(0)
            return HttpResponseRedirect(request.get_full_path())
        if 'del_volume' in request.POST:
            volname = request.POST.get('volname', '')
            vol = conn.get_volume(volname)
            vol.delete(0)
            messages.success(request, _(f"Volume: {volname} is deleted."))
            return redirect(reverse('storage', args=[compute.id, pool]))
            # return HttpResponseRedirect(request.get_full_path())
        if 'iso_upload' in request.POST:
            if str(request.FILES['file']) in conn.update_volumes():
                error_msg = _("ISO image already exist")
                messages.error(request, error_msg)
            else:
                handle_uploaded_file(path, request.FILES['file'])
                messages.success(request, _(f"ISO: {request.FILES['file']} is uploaded."))
                return HttpResponseRedirect(request.get_full_path())
        if 'cln_volume' in request.POST:
            form = CloneImage(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                img_name = data['name']
                meta_prealloc = 0
                if img_name in conn.update_volumes():
                    msg = _("Name of volume already in use")
                    messages.error(request, msg)
                if data['convert']:
                    format = data['format']
                    if data['meta_prealloc'] and data['format'] == 'qcow2':
                        meta_prealloc = True
                else:
                    format = None
                try:
                    name = conn.clone_volume(data['image'], data['name'], format, meta_prealloc)
                    messages.success(request, _(f"{data['image']} image cloned as {name} successfully"))
                    return HttpResponseRedirect(request.get_full_path())
                except libvirtError as lib_err:
                    messages.error(request, lib_err)
            else:
                for msg_err in form.errors.values():
                    messages.error(request, msg_err.as_text())

    conn.close()

    return render(request, 'storage.html', locals())


@superuser_only
def create_volume(request, compute_id, pool):
    compute = get_object_or_404(Compute, pk=compute_id)
    meta_prealloc = False

    conn = wvmStorage(compute.hostname, compute.login, compute.password, compute.type, pool)

    storages = conn.get_storages()

    form = CreateVolumeForm(request.POST or None)
    if form.is_valid():
        data = form.cleaned_data
        if data['meta_prealloc'] and data['format'] == 'qcow2':
            meta_prealloc = True

        disk_owner_uid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
        disk_owner_gid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)

        name = conn.create_volume(
            data['name'],
            data['size'],
            data['format'],
            meta_prealloc,
            disk_owner_uid,
            disk_owner_gid,
        )
        messages.success(request, _(f"Image file {name} is created successfully"))
    else:
        for msg_err in form.errors.values():
            messages.error(request, msg_err.as_text())

    return redirect(reverse('storage', args=[compute.id, pool]))


def get_volumes(request, compute_id, pool):
    """
    :param request:
    :param compute_id: compute id
    :param pool: pool name
    :return: volumes list of pool
    """
    data = {}
    compute = get_object_or_404(Compute, pk=compute_id)
    try:
        conn = wvmStorage(compute.hostname, compute.login, compute.password, compute.type, pool)
        conn.refresh()
        data['vols'] = sorted(conn.get_volumes())
    except libvirtError:
        pass
    return HttpResponse(json.dumps(data))
