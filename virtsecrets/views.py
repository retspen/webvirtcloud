from admin.decorators import superuser_only
from computes.models import Compute
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from libvirt import libvirtError
from logs.audit import audit
from vrtManager.virtsecrets import wvmSecrets

from virtsecrets.forms import AddSecret


@superuser_only
def secrets(request, compute_id):
    """The host's secrets with the VMs and pools that use them; one created,
    given a value or deleted, after which the list is read again. A value is
    never shown or logged."""
    compute = get_object_or_404(Compute, pk=compute_id)
    secrets_all = []

    try:
        conn = wvmSecrets(compute.hostname, compute.login, compute.password, compute.type)

        if request.method == "POST":
            uuid = request.POST.get("uuid", "")
            if "create" in request.POST:
                form = AddSecret(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    with audit(request, compute, f"Secret {data['usage_type']} {data['usage']}", "add"):
                        conn.create_secret(data["usage_type"], data["usage"], data["value"],
                                           data["ephemeral"], data["private"])
                else:
                    for msg_err in form.errors.values():
                        messages.error(request, msg_err.as_text())
            elif "set_value" in request.POST:
                with audit(request, compute, f"Secret {uuid}", "set value"):
                    conn.set_secret_value(uuid, request.POST.get("value", ""))
            elif "delete" in request.POST:
                with audit(request, compute, f"Secret {uuid}", "delete"):
                    conn.delete_secret(uuid)
            return HttpResponseRedirect(request.get_full_path())

        # shown only with their users: a list without them would offer to delete secrets in use
        secrets = conn.get_secrets_info()
        users = conn.get_users(secrets)
        for secret in secrets:
            secret.update(users.get(secret["uuid"], {"vms": [], "pools": []}))
        secrets_all = secrets
    except libvirtError as err:  # OperationError too: a secret in use, a Ceph key not base64
        messages.error(request, err)
        if request.method == "POST":  # a host not reached or a secret gone as well
            return HttpResponseRedirect(request.get_full_path())

    usage_choices = AddSecret.base_fields["usage_type"].choices
    return render(request, "secrets.html", {"secrets_all": secrets_all, "compute": compute,
                                            "usage_choices": usage_choices})
