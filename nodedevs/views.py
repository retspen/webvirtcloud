from admin.decorators import superuser_only
from computes.models import Compute
from django.contrib import messages
from django.shortcuts import get_object_or_404, render
from instances.models import Instance
from libvirt import libvirtError
from vrtManager.connection import wvmConnect
from vrtManager.nodedevs import node_devices


@superuser_only
def nodedevs(request, compute_id):
    """The host's PCI and USB devices: what each is, what the host has on it
    and the VMs that name it. Read only."""
    compute = get_object_or_404(Compute, pk=compute_id)
    context = {"compute": compute}
    try:
        pci, usb = node_devices(wvmConnect(compute.hostname, compute.login, compute.password, compute.type))
        vm_ids = dict(Instance.objects.filter(compute=compute).values_list("name", "id"))
        for device in pci + usb:
            device["vms"] = [{"name": name, "id": vm_ids.get(name)} for name in device["vms"]]
        groups = {}
        for device in pci:
            groups.setdefault(device["group"], []).append(device)
        context.update(devices_read=True, groups=list(groups.items()), pci_count=len(pci), usb=usb,
                       iommu=any(group is not None for group in groups))
    except libvirtError as err:  # nothing is shown without the VMs: a device would look free
        messages.error(request, err)
    return render(request, "nodedevs.html", context)
