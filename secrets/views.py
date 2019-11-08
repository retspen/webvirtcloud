from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from computes.models import Compute
from secrets.forms import AddSecret
from vrtManager.secrets import wvmSecrets
from libvirt import libvirtError


@login_required
def secrets(request, compute_id):
    """
    :param request:
    :param compute_id:
    :return:
    """

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    secrets_all = []
    error_messages = []
    compute = get_object_or_404(Compute, pk=compute_id)

    try:
        conn = wvmSecrets(compute.hostname,
                          compute.login,
                          compute.password,
                          compute.type)
        secrets = conn.get_secrets()
        for uuid in secrets:
            secrt = conn.get_secret(uuid)
            try:
                secret_value = conn.get_secret_value(uuid)
            except libvirtError as lib_err:
                secret_value = None
            secrets_all.append({'usage': secrt.usageID(),
                                'uuid': secrt.UUIDString(),
                                'usageType': secrt.usageType(),
                                'value': secret_value
                                })
        if request.method == 'POST':
            if 'create' in request.POST:
                form = AddSecret(request.POST)
                if form.is_valid():
                    data = form.cleaned_data
                    conn.create_secret(data['ephemeral'], data['private'], data['usage_type'], data['data'])
                    return HttpResponseRedirect(request.get_full_path())
                else:
                    for msg_err in form.errors.values():
                        error_messages.append(msg_err.as_text())
            if 'delete' in request.POST:
                uuid = request.POST.get('uuid', '')
                conn.delete_secret(uuid)
                return HttpResponseRedirect(request.get_full_path())
            if 'set_value' in request.POST:
                uuid = request.POST.get('uuid', '')
                value = request.POST.get('value', '')
                conn.set_secret_value(uuid, value)
                return HttpResponseRedirect(request.get_full_path())
    except libvirtError as err:
        error_messages.append(err)

    return render(request, 'secrets.html', locals())
