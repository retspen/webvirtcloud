from django import template
from django.utils.crypto import salted_hmac

from instances.states import allowed_actions, manages, state_label

register = template.Library()


@register.simple_tag
def vm_state(state):
    """{% vm_state state as label_color %}: label and Bootstrap color."""
    return state_label(state)


@register.simple_tag(takes_context=True)
def vm_actions(context, instance):
    """{% vm_actions instance as actions %}: the actions this user may use now."""
    if not instance.info:
        return set()
    return allowed_actions(context["request"].user, instance, instance.info[0])


@register.simple_tag(takes_context=True)
def vm_manages(context, instance):
    """{% vm_manages instance as manages %}: the user is a superuser or one of the VM's owners."""
    return manages(context["request"].user, instance)


@register.filter
def disk_seen(disk):
    """{{ disk|disk_seen }}: the fingerprint of the disk's file as the page
    shows it, which a form sends back; the file is not shown. Keyed: an owner
    cannot try likely paths against it."""
    return salted_hmac("instances.disk_seen", disk["path"] or "", algorithm="sha256").hexdigest()


@register.filter
def running_limit(disk, instance):
    """{{ disk|running_limit:instance }}: the running VM's I/O limit of disk, (IOPS, MiB/s, set in the
    XML), when it differs from the next start's the Disks tab shows; else None."""
    running = instance.live_iotune.get(disk["dev"])
    if running is None or running == (disk.get("iops", 0), disk.get("mibps", 0), disk.get("iotune_custom", False)):
        return None
    return running

