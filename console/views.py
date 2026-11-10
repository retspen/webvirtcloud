# pylint: disable=no-name-in-module,no-member

import functools
import json
import logging
from pathlib import Path

from appsettings.settings import app_settings
from console import tokens
from django.conf import settings
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from instances.models import Instance
from instances.utils import can_open_console
from libvirt import libvirtError
from operations.utils import safe_text
from vrtManager.connection import CONN_TCP, CONN_TLS
from vrtManager.instance import wvmInstance
from vrtManager.util import is_loopback
from webvirtcloud.middleware import error_text

logger = logging.getLogger(__name__)

# one file a layout, written by dev/console_layout.py
LAYOUTS_DIR = Path(__file__).resolve().parent / "layouts"


@functools.cache
def keyboard_layouts():
    """The keyboard layouts the VNC console types text with, US first, then
    by name: {id: {"name": ..., "keys": {DOM code: [plain, Shift, AltGr,
    Shift+AltGr]}}}."""
    layouts = {}
    for path in LAYOUTS_DIR.glob("*.json"):
        layout = json.loads(path.read_text())
        layouts[path.stem] = {"name": layout["name"], "keys": layout["keys"]}
    us = layouts.pop("us")
    return {"us": us, **dict(sorted(layouts.items(), key=lambda item: item[1]["name"]))}


def console(request, compute_id, uuid):
    """The console page of the VM with this UUID on this compute. A console
    that cannot open gets a page that says why, and no console client."""
    instance = Instance.objects.filter(compute_id=compute_id, uuid=uuid).first()
    if instance is None:
        # migrated since the page was opened: a reconnect finds the VM on its
        # new compute, when it is the only one with that UUID the user may open
        moved = [vm for vm in Instance.objects.filter(uuid=uuid) if can_open_console(request.user, vm)]
        if len(moved) == 1:
            return redirect("console", moved[0].compute_id, uuid)
    # Same answer for "no such VM" and "not allowed", so the response
    # does not reveal whether a VM exists.
    if instance is None or not can_open_console(request.user, instance):
        console_error = _("User does not have permission to access console or host/instance not exist")
        return render(request, "console-error.html", {"console_error": console_error}, status=403)

    try:
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
    except libvirtError as err:
        # the host or the VM could not be read: the page says that, not to check the console settings
        logger.warning("Console of %s on %s: %s", instance.name, instance.compute.name, safe_text(err))
        return render(request, "console-error.html", {"instance": instance, "console_error": error_text(request, err)})
    except (ValueError, IndexError):
        running = unreachable = False
        console_type = None
        console_passwd = None

    if console_type is None:
        console_error = _("Fail to get console. Please check the console configuration of your VM.")
    elif not running:  # a shut-off VM has no console to connect to
        console_error = _("The VM is not running: start it to open its console.")
    elif console_type == "vnc" and unreachable:
        console_error = _(
            "This console listens only on its host, which the panel reaches over TCP or TLS. "
            "Let the console listen on all interfaces in the VM's console settings, "
            "or add the host as an SSH host."
        )
    elif console_type == "pty" and not settings.SERIAL_CONSOLE_ENABLED:
        console_error = _(
            "Serial console is disabled on this server. "
            "Please switch VM graphics to VNC or ask an administrator."
        )
    elif console_type not in ("vnc", "pty"):
        console_error = _(
            "Console type '%(type)s' is not supported. Please switch the VM graphics to VNC."
        ) % {"type": console_type}
    else:
        console_error = None
    if console_error:
        return render(request, "console-error.html", {"instance": instance, "console_error": console_error})

    # the console daemons' credential for this page
    token = tokens.sign(compute_id, uuid, request.user.id, console_type)
    if console_type == "pty":
        return render(request, "console-xterm.html", {"instance": instance, "token": token})

    # how the VNC page starts (Settings > Console); its View menu changes them
    if app_settings.CONSOLE_RESIZE_SESSION == "True":
        resize = "remote"
    elif app_settings.CONSOLE_SCALE == "True":
        resize = "scale"
    else:
        resize = "off"
    vnc = {
        "token": token,
        # without the permission the VNC server asks the user for it
        "password": console_passwd if request.user.has_perm("instances.passwordless_console") else None,
        "resize": resize,
        "clip": app_settings.CONSOLE_CLIP_VIEWPORT == "True",
        "viewOnly": app_settings.CONSOLE_VIEW_ONLY == "True",
    }
    return render(request, "console-vnc.html", {"instance": instance, "vnc": vnc, "layouts": keyboard_layouts()})
