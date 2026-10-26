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
    VIR_SECRET_USAGE_TYPE_VTPM,
    libvirtError,
)
from logs.audit import audit
from vrtManager.util import OperationError
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
        VIR_SECRET_USAGE_TYPE_VTPM: "vtpm",
    }
    # the create dialog offers the usage types the form takes
    usage_choices = AddSecret.base_fields["usage_type"].choices

    try:
        conn = wvmSecrets(
            compute.hostname, compute.login, compute.password, compute.type
        )
        secrets = conn.get_secrets()

        for uuid in secrets:
            secrt = conn.get_secret(uuid)
            secrets_all.append(
                {
                    "usage": secrt.usageID(),
                    "uuid": secrt.UUIDString(),
                    "usageType": secret_usage_types[secrt.usageType()],
                }
            )
        if request.method == "POST":
            if "create" in request.POST:
                form = AddSecret(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    with audit(request, compute, f"Secret {data['usage_type']} {data['data']}", "add"):
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
                try:
                    with audit(request, compute, f"Secret {uuid}", "delete"):
                        conn.delete_secret(uuid)
                except OperationError as err:  # a VM disk or a pool needs it
                    messages.error(request, str(err))
                return HttpResponseRedirect(request.get_full_path())
            if "set_value" in request.POST:
                uuid = request.POST.get("uuid", "")
                value = request.POST.get("value", "")
                try:
                    with audit(request, compute, f"Secret {uuid}", "set value"):
                        conn.set_secret_value(uuid, value)
                except Exception as err:
                    messages.error(request, err)
                return HttpResponseRedirect(request.get_full_path())
    except libvirtError as err:
        messages.error(request, err)

    return render(request, "secrets.html", locals())
