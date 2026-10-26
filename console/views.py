# pylint: disable=no-name-in-module,no-member
import re

from appsettings.settings import app_settings
from console import tokens
from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired
from django.http.response import HttpResponseForbidden
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from instances.models import Instance
from instances.utils import can_open_console
from libvirt import libvirtError
from vrtManager.instance import wvmInstance


def to_bool(val, default=False):
    if val is None:
        return default
    return str(val).strip().lower() in ("true", "1", "yes")


def console(request):
    """
    :param request:
    :return:
    """
    console_error = None
    token = ""
    view_type = "lite"
    view_only = to_bool(app_settings.CONSOLE_VIEW_ONLY, default=False)
    scale = to_bool(app_settings.CONSOLE_SCALE, default=False)
    resize_session = to_bool(app_settings.CONSOLE_RESIZE_SESSION, default=False)
    clip_viewport = to_bool(app_settings.CONSOLE_CLIP_VIEWPORT, default=False)

    if request.method == "GET":
        token = request.GET.get("token", token)
        view_type = (
            "full"
            if str(request.GET.get("view", view_type)).strip().lower() == "full"
            else "lite"
        )
        if "view_only" in request.GET:
            view_only = to_bool(request.GET.get("view_only"), default=view_only)
        if "scale" in request.GET:
            scale = to_bool(request.GET.get("scale"), default=scale)
        if "resize_session" in request.GET:
            resize_session = to_bool(
                request.GET.get("resize_session"), default=resize_session
            )
        if "clip_viewport" in request.GET:
            clip_viewport = to_bool(
                request.GET.get("clip_viewport"), default=clip_viewport
            )

    signer = tokens.SIGNER
    host = None
    uuid = None

    if token:
        try:
            unsigned = signer.unsign(token, max_age=120)
            parts = unsigned.split(":")
            if len(parts) >= 2:
                host = int(parts[0])
                uuid = parts[1]
        except (BadSignature, SignatureExpired, ValueError, TypeError):
            pass

        if host is None or uuid is None:
            try:
                temptoken = token.split("-", 1)
                host = int(temptoken[0])
                uuid = temptoken[1]
            except (ValueError, IndexError):
                host = None
                uuid = None

    try:
        if host is None or uuid is None:
            raise ValueError("Invalid token")

        instance = Instance.objects.filter(compute_id=host, uuid=uuid).first()
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
        token = signer.sign(f"{host}:{uuid}:{request.user.id}")

        conn = wvmInstance(
            instance.compute.hostname,
            instance.compute.login,
            instance.compute.password,
            instance.compute.type,
            instance.name,
            uuid=instance.uuid,
        )
        console_type = conn.get_console_type()
        console_websocket_port = conn.get_console_websocket_port()
        console_passwd = conn.get_console_passwd()
        running = conn.instance.isActive()
    except (libvirtError, ValueError, IndexError, Instance.DoesNotExist):
        running = False
        console_type = None
        console_websocket_port = None
        console_passwd = None

    ws_public_port = getattr(settings, "WS_PUBLIC_PORT", 6080)
    ws_public_host = getattr(settings, "WS_PUBLIC_HOST", None)
    ws_public_path = getattr(settings, "WS_PUBLIC_PATH", "/")

    ws_port = console_websocket_port if console_websocket_port else ws_public_port
    ws_host = ws_public_host if ws_public_host else request.get_host()
    ws_path = ws_public_path if ws_public_path else "/"

    if ":" in ws_host:
        ws_host = re.sub(":[0-9]+", "", ws_host)

    if ws_path:
        ws_path = ws_path.strip("/") + "/" if ws_path.strip("/") else ""

    if console_type and not running:  # a shut-off VM has no console to connect to
        console_error = _("The VM is not running: start it to open its console.")
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
