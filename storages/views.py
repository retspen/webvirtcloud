import contextlib
import logging

from admin.decorators import superuser_only
from appsettings.settings import app_settings
from computes.models import Compute
from computes.utils import libvirt_compute_lock
from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from libvirt import libvirtError
from operations import claims, jobs
from operations.utils import busy_message
from logs.audit import audit, failed

from vrtManager.util import OperationError
from vrtManager.storage import wvmStorage, wvmStorages

from storages.forms import AddStgPool, CloneImage, CreateVolumeForm
from storages.jobs import is_iso
from storages.upload import write_chunk


def _handle_iso_upload(request, conn, compute, pool):
    file_chunk = request.FILES.get("file")
    if not file_chunk:
        return JsonResponse({"error": _("No file chunk was submitted.")}, status=400)

    try:
        chunk_index = int(request.POST.get("chunk_index", 0))
        total_chunks = int(request.POST.get("total_chunks", 1))
    except (ValueError, TypeError):
        return JsonResponse({"error": _("Invalid chunk parameters.")}, status=400)
    if chunk_index < 0 or chunk_index >= total_chunks:
        return JsonResponse({"error": _("Invalid chunk index or total chunks.")}, status=400)

    try:
        file_size = int(request.POST.get("file_size", ""))
    except (ValueError, TypeError):
        return JsonResponse({"error": _("Invalid file size.")}, status=400)

    try:
        op = write_chunk(request, conn, compute, pool, request.POST.get("upload_id", ""),
                         {"name": request.POST.get("file_name", ""), "size": file_size, "chunks": total_chunks},
                         chunk_index, file_chunk)
    except claims.Busy as busy:
        if busy.blocker is not None:  # another job holds the pool or the name
            return JsonResponse({"error": busy_message(busy, request.user)}, status=400)
        return JsonResponse({"error": _("Upload session is busy. Please retry.")}, status=429)
    except FileExistsError:
        return JsonResponse({"error": _("ISO image already exists")}, status=400)
    except (ValueError, jobs.SubmissionConflict, OperationError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        logging.getLogger(__name__).exception("ISO upload chunk failed")
        return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"success": True, "job": str(op.pk)})


@superuser_only
def storages(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    compute = get_object_or_404(Compute, pk=compute_id)
    errors = False

    try:
        conn = wvmStorages(
            compute.hostname, compute.login, compute.password, compute.type
        )
        storages = conn.get_storages_info()
        secrets = conn.get_secrets()

        if request.method == "POST":
            if "create" in request.POST:
                form = AddStgPool(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    if data["name"] in [stg["name"] for stg in storages]:
                        msg = _("Pool name already use")
                        messages.error(request, msg)
                        failed(request, compute, f"Storage pool {data['name']}", "add", "name already in use")
                        errors = True
                    if data["stg_type"] == "rbd":
                        if not data["secret"]:
                            msg = _("You need create secret for pool")
                            messages.error(request, msg)
                            errors = True
                        if (
                            not data["ceph_pool"]
                            and not data["ceph_host"]
                            and not data["ceph_user"]
                        ):
                            msg = _("You need input all fields for creating ceph pool")
                            messages.error(request, msg)
                            errors = True
                    if not errors:
                        with audit(request, compute, f"Storage pool {data['name']}", "add"):
                            if data["stg_type"] == "rbd":
                                conn.create_storage_ceph(
                                    data["stg_type"],
                                    data["name"],
                                    data["ceph_pool"],
                                    data["ceph_host"],
                                    data["ceph_user"],
                                    data["secret"],
                                )
                            elif data["stg_type"] == "netfs":
                                conn.create_storage_netfs(
                                    data["stg_type"],
                                    data["name"],
                                    data["netfs_host"],
                                    data["source"],
                                    data["source_format"],
                                    data["target"],
                                )
                            else:
                                conn.create_storage(
                                    data["stg_type"],
                                    data["name"],
                                    data["source"],
                                    data["target"],
                                )
                        return HttpResponseRedirect(
                            reverse("storage", args=[compute_id, data["name"]])
                        )
                else:
                    for msg_err in form.errors.values():
                        messages.error(request, msg_err.as_text())
        conn.close()
    except libvirtError as lib_err:
        messages.error(request, lib_err)

    return render(request, "storages.html", locals())


@superuser_only
def storage(request, compute_id, pool):
    """
    :param request:
    :param compute_id:
    :param pool:
    :return:
    """
    compute = get_object_or_404(Compute, pk=compute_id)
    meta_prealloc = False
    form = CreateVolumeForm()

    conn = wvmStorage(
        compute.hostname, compute.login, compute.password, compute.type, pool
    )

    if request.method == "POST" and "iso_upload" in request.POST:
        try:
            return _handle_iso_upload(request, conn, compute, pool)
        finally:
            conn.close()

    storages = conn.get_storages()
    state = conn.is_active()
    # first: it refreshes the pool, and libvirt measures a pool's space only then
    volumes = conn.update_volumes() if state else None
    for volume in volumes or []:
        volume["iso"] = is_iso(volume["name"])
    try:
        size, free = conn.get_size()
        status = conn.get_status()
        used = size - free
        if state and size:  # an iSCSI pool without LUNs has no size
            percent = (used * 100) // size
        else:
            percent = 0
    except libvirtError:  # both read the pool's info: the page says it could not be read
        size = free = used = percent = status = None

    path = conn.get_target_path()
    type = conn.get_type()
    autostart = conn.get_autostart()

    if request.method == "POST":
        subject = f"Storage pool {pool}"
        if "start" in request.POST:
            with audit(request, compute, subject, "start"):
                conn.start()
            return HttpResponseRedirect(request.get_full_path())
        if "stop" in request.POST:
            try:
                with audit(request, compute, subject, "stop"):
                    conn.stop()
            except OperationError as err:  # a running VM's disk is in it
                messages.error(request, str(err))
            return HttpResponseRedirect(request.get_full_path())
        if "delete" in request.POST:
            try:
                with audit(request, compute, subject, "delete"):
                    conn.delete()
            except OperationError as err:  # a VM names it for a disk
                messages.error(request, str(err))
                return HttpResponseRedirect(request.get_full_path())
            return HttpResponseRedirect(reverse("storages", args=[compute_id]))
        if "set_autostart" in request.POST:
            with audit(request, compute, subject, "autostart on"):
                conn.set_autostart(1)
            return HttpResponseRedirect(request.get_full_path())
        if "unset_autostart" in request.POST:
            with audit(request, compute, subject, "autostart off"):
                conn.set_autostart(0)
            return HttpResponseRedirect(request.get_full_path())
        if "del_volume" in request.POST:
            volname = request.POST.get("volname", "")
            try:
                # no VM operation attaches it between the check and the delete
                with audit(request, compute, subject, f"delete volume {volname}"), libvirt_compute_lock(compute):
                    conn.del_volume(volname)
            except OperationError as err:
                messages.error(request, str(err))
            except claims.Busy as busy:
                messages.error(request, busy_message(busy, request.user))
            else:
                messages.success(
                    request, _("Volume: %(vol)s is deleted.") % {"vol": volname}
                )
            return redirect(reverse("storage", args=[compute.id, pool]))
            # return HttpResponseRedirect(request.get_full_path())
        if "cln_volume" in request.POST:
            form = CloneImage(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                try:
                    with audit(request, compute, f"Storage pool {pool}",
                               f"clone volume {data['image']} as {data['name']}") as entry:
                        op = jobs.submit("volume.clone", request.user, {"compute": compute.id, "pool": pool, **data},
                                         request.POST.get("submission_key", ""))
                        entry.skip = True  # the job writes its row when it ends
                except claims.Busy as busy:
                    messages.error(request, busy_message(busy, request.user))
                except (jobs.SubmissionConflict, OperationError, libvirtError) as err:
                    messages.error(request, str(err))
                else:
                    messages.info(request, _("The volume is being cloned; follow it in the job panel."))
                    jobs.remember_job(request, op)
            else:
                for msg_err in form.errors.values():
                    messages.error(request, msg_err.as_text())
            return redirect(reverse("storage", args=[compute.id, pool]))

    job_resource = claims.pool_key(compute.id, pool)
    conn.close()

    return render(request, "storage.html", locals())


@superuser_only
def create_volume(request, compute_id, pool):
    """
    :param request:
    :param compute_id: compute id
    :param pool: pool name
    :return:
    """
    compute = get_object_or_404(Compute, pk=compute_id)
    meta_prealloc = False

    conn = wvmStorage(
        compute.hostname, compute.login, compute.password, compute.type, pool
    )

    form = CreateVolumeForm(request.POST or None)
    if form.is_valid():
        data = form.cleaned_data
        if data["meta_prealloc"] and data["format"] == "qcow2":
            meta_prealloc = True

        disk_owner_uid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID)
        disk_owner_gid = int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID)

        with audit(request, compute, f"Storage pool {pool}", f"add volume {data['name']}") as entry:
            name = conn.create_volume(
                data["name"],
                data["size"],
                data["format"],
                meta_prealloc,
                disk_owner_uid,
                disk_owner_gid,
            )
            entry.action = f"add volume {name}"
        messages.success(
            request, _("Image file %(name)s is created successfully") % {"name": name}
        )
    else:
        for msg_err in form.errors.values():
            messages.error(request, msg_err.as_text())

    return redirect(reverse("storage", args=[compute.id, pool]))


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
        conn = wvmStorage(
            compute.hostname, compute.login, compute.password, compute.type, pool
        )
        with contextlib.suppress(libvirtError):  # refused while a volume is cloned in the pool
            conn.refresh()
        data["vols"] = sorted(conn.get_volumes())
    except libvirtError as err:
        # do not answer 200 with an empty list when the listing failed: the
        # caller cannot tell "no volumes" from "could not read the pool"
        return JsonResponse({"error": str(err)}, status=400)
    return JsonResponse(data)
