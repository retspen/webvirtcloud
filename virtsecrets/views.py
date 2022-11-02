from admin.decorators import superuser_only
from computes.models import Compute
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from libvirt import (
    VIR_SECRET_USAGE_TYPE_CEPH,
    VIR_SECRET_USAGE_TYPE_ISCSI,
    VIR_SECRET_USAGE_TYPE_NONE,
    VIR_SECRET_USAGE_TYPE_TLS,
    VIR_SECRET_USAGE_TYPE_VOLUME,
    libvirtError,
)
from vrtManager.virtsecrets import wvmSecrets

from virtsecrets.forms import AddSecret


@superuser_only
def secrets(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    secrets_all = []
    compute = get_object_or_404(Compute, pk=compute_id)
    secret_usage_types = {
        VIR_SECRET_USAGE_TYPE_NONE: "none",
        VIR_SECRET_USAGE_TYPE_VOLUME: "volume",
        VIR_SECRET_USAGE_TYPE_CEPH: "ceph",
        VIR_SECRET_USAGE_TYPE_ISCSI: "iscsi",
        VIR_SECRET_USAGE_TYPE_TLS: "tls",
    }

    try:
        conn = wvmSecrets(
            compute.hostname, compute.login, compute.password, compute.type
        )
        secrets = conn.get_secrets()

        for uuid in secrets:
            secrt = conn.get_secret(uuid)
            try:
                secrt_value = conn.get_secret_value(uuid)
            except libvirtError:
                secrt_value = None
            secrets_all.append(
                {
                    "usage": secrt.usageID(),
                    "uuid": secrt.UUIDString(),
                    "usageType": secret_usage_types[secrt.usageType()],
                    "value": secrt_value,
                }
            )
        if request.method == "POST":
            if "create" in request.POST:
                form = AddSecret(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    conn.create_secret(
                        data["ephemeral"],
                        data["private"],
                        data["usage_type"],
                        data["data"],
                    )
                    return HttpResponseRedirect(request.get_full_path())
                else:
                    for msg_err in form.errors.values():
                        messages.error(request, msg_err.as_text())
            if "delete" in request.POST:
                uuid = request.POST.get("uuid", "")
                conn.delete_secret(uuid)
                return HttpResponseRedirect(request.get_full_path())
            if "set_value" in request.POST:
                uuid = request.POST.get("uuid", "")
                value = request.POST.get("value", "")
                try:
                    conn.set_secret_value(uuid, value)
                except Exception as err:
                    messages.error(request, err)
                return HttpResponseRedirect(request.get_full_path())
    except libvirtError as err:
        messages.error(request, err)

    return render(request, "secrets.html", locals())
