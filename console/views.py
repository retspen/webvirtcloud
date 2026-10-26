# pylint: disable=no-name-in-module,no-member

from appsettings.settings import app_settings
from console import tokens
from django.conf import settings
from django.http.response import HttpResponseForbidden
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from instances.models import Instance
from instances.utils import can_open_console
from libvirt import libvirtError
from vrtManager.connection import CONN_TCP, CONN_TLS
from vrtManager.instance import wvmInstance
from vrtManager.util import is_loopback


def to_bool(val, default=False):
    if val is None:
        return default
    return str(val).strip().lower() in ("true", "1", "yes")


def console(request, compute_id, uuid):
    """The console page of the VM with this UUID on this compute. The page's
    query gives the view (lite or full) and its display options."""
    console_error = None
    token = ""
    view_type = "full" if request.GET.get("view", "").strip().lower() == "full" else "lite"
    view_only = to_bool(request.GET.get("view_only"), default=to_bool(app_settings.CONSOLE_VIEW_ONLY))
    scale = to_bool(request.GET.get("scale"), default=to_bool(app_settings.CONSOLE_SCALE))
    resize_session = to_bool(request.GET.get("resize_session"), default=to_bool(app_settings.CONSOLE_RESIZE_SESSION))
    clip_viewport = to_bool(request.GET.get("clip_viewport"), default=to_bool(app_settings.CONSOLE_CLIP_VIEWPORT))

    try:
        instance = Instance.objects.filter(compute_id=compute_id, uuid=uuid).first()
        if instance is None and request.user.is_superuser:
            raise Instance.DoesNotExist
        # Same answer for "no such VM" and "not allowed", so the response
        # does not reveal whether a VM exists.
        if instance is None or not can_open_console(request.user, instance):
            console_error = _(
                "User does not have permission to access console or host/instance not exist"
            )
            return HttpResponseForbidden(console_error)

        # Generate secure signed token for noVNC daemon
        token = tokens.SIGNER.sign(f"{compute_id}:{uuid}:{request.user.id}")

        conn = wvmInstance(
            instance.compute.hostname,
            instance.compute.login,
            instance.compute.password,
            instance.compute.type,
            instance.name,
            uuid=instance.uuid,
        )
        console_type = conn.get_console_type()
        console_passwd = conn.get_console_passwd()
        running = conn.instance.isActive()
        # novncd reaches a console that listens on its host's loopback only
        # through SSH (or on this host); the running VM's listener, as novncd sees it
        unreachable = instance.compute.type in (CONN_TCP, CONN_TLS) and bool(
            conn.get_console_socket() or is_loopback(conn.get_console_listener_addr())
        )
    except (libvirtError, ValueError, IndexError, Instance.DoesNotExist):
        running = unreachable = False
        console_type = None
        console_passwd = None

    if console_type and not running:  # a shut-off VM has no console to connect to
        console_error = _("The VM is not running: start it to open its console.")
        response = render(request, "console-vnc-lite.html", locals())
    elif console_type == "vnc" and unreachable:
        console_error = _(
            "This console listens only on its host, which the panel reaches over TCP or TLS. "
            "Let the console listen on all interfaces in the VM's console settings, "
            "or add the host as an SSH host."
        )
        response = render(request, "console-vnc-lite.html", locals())
    elif console_type == "vnc":
        console_page = "console-vnc-" + view_type + ".html"
        response = render(request, console_page, locals())
    elif console_type == "pty" and not settings.SERIAL_CONSOLE_ENABLED:
        console_error = _(
            "Serial console is disabled on this server. "
            "Please switch VM graphics to VNC or ask an administrator."
        )
        response = render(request, "console-vnc-lite.html", locals())
    elif console_type == "pty":
        response = render(request, "console-xterm.html", locals())
    else:
        if console_type is None:
            console_error = _(
                "Fail to get console. Please check the console configuration of your VM."
            )
        else:
            console_error = _(
                "Console type '%(type)s' is not supported. Please switch the VM graphics to VNC."
            ) % {"type": console_type}
        response = render(request, "console-vnc-lite.html", locals())
    return response
