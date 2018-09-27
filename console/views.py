import re
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from instances.models import Instance
from vrtManager.instance import wvmInstance
from webvirtcloud.settings import WS_PORT
from webvirtcloud.settings import WS_PUBLIC_HOST
from webvirtcloud.settings import WS_PUBLIC_PORT
from webvirtcloud.settings import WS_PUBLIC_PATH
from libvirt import libvirtError


@login_required
def console(request):
    """
    :param request:
    :return:
    """
    console_error = None

    if request.method == 'GET':
        token = request.GET.get('token', '')
        view_type = request.GET.get('view', 'lite')

    try:
        temptoken = token.split('-', 1)
        host = int(temptoken[0])
        uuid = temptoken[1]
        instance = Instance.objects.get(compute_id=host, uuid=uuid)
        conn = wvmInstance(instance.compute.hostname,
                           instance.compute.login,
                           instance.compute.password,
                           instance.compute.type,
                           instance.name)
        console_type = conn.get_console_type()
        console_websocket_port = conn.get_console_websocket_port()
        console_passwd = conn.get_console_passwd()
    except libvirtError as lib_err:
        console_type = None
        console_websocket_port = None
        console_passwd = None

    ws_port = console_websocket_port if console_websocket_port else WS_PUBLIC_PORT
    ws_host = WS_PUBLIC_HOST if WS_PUBLIC_HOST else request.get_host()
    ws_path = WS_PUBLIC_PATH if WS_PUBLIC_PATH else '/'

    if ':' in ws_host:
        ws_host = re.sub(':[0-9]+', '', ws_host)

    console_page = "console-" + console_type + "-" + view_type + ".html"
    if console_type == 'vnc' or console_type == 'spice':
        response = render(request, console_page, locals())
    else:
        console_error = "Console type: %s no support" % console_type
        response = render(request, 'console-vnc-lite.html', locals())

    response.set_cookie('token', token)
    return response
