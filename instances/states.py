"""
libvirt VM states: their labels, and the actions each one allows a user.
The lists and the VM page use these through templatetags/vm_states.py.
"""

import libvirt
from django.utils.translation import gettext_lazy as _

# state (virDomainState): label, Bootstrap color
STATES = {
    0: (_("No state"), "secondary"),
    1: (_("Active"), "success"),
    2: (_("Blocked"), "success"),  # running, waiting for a resource
    3: (_("Suspended"), "warning"),
    4: (_("Shutting down"), "warning"),
    5: (_("Off"), "secondary"),  # shut off is not a fault
    6: (_("Crashed"), "danger"),
    7: (_("PM suspended"), "warning"),  # suspended by the guest
}
UNKNOWN = (_("Unknown"), "secondary")  # the VM cannot be read

# (state, reason): why a VM stopped or paused that nobody asked for; the
# ordinary reasons (a user, a migration, a snapshot) are not told
REASONS = {
    # a write error, or a read error where the disk's policy is to stop
    (libvirt.VIR_DOMAIN_PAUSED, libvirt.VIR_DOMAIN_PAUSED_IOERROR): _("Paused by a disk error"),
    (libvirt.VIR_DOMAIN_PAUSED, libvirt.VIR_DOMAIN_PAUSED_WATCHDOG): _("Paused by its watchdog"),
    (libvirt.VIR_DOMAIN_PAUSED, libvirt.VIR_DOMAIN_PAUSED_CRASHED): _("Paused: the guest crashed"),
    (libvirt.VIR_DOMAIN_PAUSED, libvirt.VIR_DOMAIN_PAUSED_POSTCOPY_FAILED): _("Paused: its migration failed midway"),
    # the guest, or its QEMU process (killed on the host: out of memory)
    (libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_SHUTOFF_CRASHED): _("Stopped: it crashed"),
    # libvirt could not take it back after restarting
    (libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_SHUTOFF_DAEMON): _("Stopped by libvirt"),
    (libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_SHUTOFF_FAILED): _("Stopped: it failed to start"),
    (libvirt.VIR_DOMAIN_CRASHED, libvirt.VIR_DOMAIN_CRASHED_PANICKED): _("The guest's kernel panicked"),
}

RUNNING = {"suspend", "poweroff", "powercycle", "force_off", "console"}
# the states the power tab shows as its strip: active, blocked, suspended, off, PM suspended
POWER_STATES = (1, 2, 3, 5, 7)
STATE_ACTIONS = {
    1: RUNNING,
    2: RUNNING,
    3: {"resume", "force_off"},
    5: {"poweron"},
    # shutting down, crashed, suspended by the guest: a forced power off ends
    # it, and the VM can be started again
    4: {"force_off"},
    6: {"force_off"},
    7: {"force_off"},
}
SUPERUSER_ONLY = {"suspend", "resume"}  # their views are for superusers


def state_label(state):
    """(label, color) of a state; None for a VM that cannot be read."""
    return UNKNOWN if state is None else STATES.get(state, STATES[0])

# a disk error (virDomainGetDiskErrors) of a VM paused by one
DISK_ERRORS = {
    libvirt.VIR_DOMAIN_DISK_ERROR_NO_SPACE: _("%(dev)s: its storage has no free space"),
    libvirt.VIR_DOMAIN_DISK_ERROR_UNSPEC: _("%(dev)s: an I/O error"),
}


def state_reason(state, reason):
    """Why the VM is in its state, when that is a fault (REASONS); else None."""
    return REASONS.get((state, reason))


def manages(user, instance):
    """Superusers and a VM's owners: the users its power actions are for."""
    # the lists prefetch userinstance_set
    return user.is_superuser or any(ui.user_id == user.id for ui in instance.userinstance_set.all())


def allowed_actions(user, instance, state):
    """
    The power actions the state allows and the user may use: superusers all,
    a VM's owners all but suspend and resume, nobody else any (the
    view_instances permission is read-only). A VM suspended by an
    administrator offers its owner nothing. A template is not started (a
    power cycle starts it again) but cloned, by anyone with the clone
    permission who sees it.
    """
    if state == 5 and instance.is_template:
        return {"clone"} if user.has_perm("instances.clone_instances") else set()
    if user.is_superuser:
        actions = STATE_ACTIONS.get(state, set())
    elif not manages(user, instance) or state == 3:
        return set()
    else:
        actions = STATE_ACTIONS.get(state, set()) - SUPERUSER_ONLY
    return actions - {"powercycle"} if instance.is_template else actions
