from django.utils.translation import gettext_lazy as _
from libvirt import VIR_CONNECT_LIST_NODE_DEVICES_CAP_USB_DEV, VIR_ERR_NO_NODE_DEVICE, libvirtError
from lxml import etree

from vrtManager import util

# PCI base classes by their code (the class's first byte)
PCI_CLASSES = {
    0x01: _("Storage controller"),
    0x02: _("Network controller"),
    0x03: _("Display controller"),
    0x04: _("Multimedia controller"),
    0x06: _("Bridge"),
    0x0C: _("Serial bus controller"),
}

# USB interface classes by their code
USB_CLASSES = {
    0x01: _("Audio"),
    0x02: _("Communications"),
    0x03: _("Human interface"),
    0x06: _("Imaging"),
    0x07: _("Printer"),
    0x08: _("Mass storage"),
    0x09: _("Hub"),
    0x0A: _("Communications data"),
    0x0B: _("Smart card"),
    0x0E: _("Video"),
    0xE0: _("Wireless"),
    0xFF: _("Vendor specific"),
}

USB_HUB = 0x09


def pci_address(domain, bus, slot, function):
    """A PCI address as lspci writes it, from its parts as integers or as
    libvirt's hex text (0x0000)."""
    domain, bus, slot, function = (int(str(part), 0) for part in (domain, bus, slot, function))
    return f"{domain:04x}:{bus:02x}:{slot:02x}.{function:x}"


def host_resources(name, nodes, children):
    """What the host itself has on the device named name or below it: its
    network interfaces, block devices and graphics cards, by name. Giving
    the device to a VM takes them from the host."""
    found = []
    for child in children.get(name, []):
        cap = nodes[child].find("capability")
        if cap.get("type") == "net":
            found.append(cap.findtext("interface"))
        elif cap.get("type") == "storage":
            found.append(cap.findtext("block"))
        elif cap.get("type") == "drm" and cap.findtext("type") == "primary":
            found.append(nodes[child].xpath("string(devnode[@type='dev'])"))
        found.extend(host_resources(child, nodes, children))
    return found


def usb_selector(source):
    """(vendor, product, (bus, device) or None) of a USB <hostdev>'s <source>,
    the parts libvirt picks a device by. An address libvirt resolved for a
    running VM (autoAddress, in its migratable XML) is not one of them."""
    address = source.find("address")
    given = address is not None and source.get("autoAddress") != "yes"
    return (source.xpath("string(vendor/@id)").lower(), source.xpath("string(product/@id)").lower(),
            (int(address.get("bus")), int(address.get("device"))) if given else None)


def hostdev_users(trees):
    """What a VM's definitions give it of the host: PCI addresses (of a
    <hostdev>, or of a NIC that is a host device) and USB selectors
    (usb_selector)."""
    pci, usb = set(), []
    for tree in trees:
        for address in tree.xpath("devices/hostdev[@mode='subsystem'][@type='pci']/source/address"
                                  " | devices/interface[@type='hostdev']/source/address"
                                  " | devices/interface/actual[@type='hostdev']/source/address"):
            pci.add(pci_address(address.get("domain", "0"), address.get("bus"), address.get("slot"), address.get("function")))
        usb.extend(usb_selector(source) for source in tree.xpath("devices/hostdev[@mode='subsystem'][@type='usb']/source"))
    return pci, usb


def usb_named(selector, model, address):
    """How a USB selector names the device of model at address: "address"
    (its address, and its IDs where given), "model" (its IDs, no address:
    any device of the model may be taken) or None."""
    vendor, product, selected = selector
    ids_match = (not vendor or vendor == model[0]) and (not product or product == model[1])
    if not ids_match:
        return None
    if selected == address:
        return "address"
    return "model" if selected is None else None


def device_problems(label, vms, resources, vm):
    """Why a host device cannot be given to the VM named vm: the other VMs
    that name it, and what the host has on it."""
    problems = []
    if others := sorted(set(vms) - {vm}):
        problems.append(f"{label} is given to {', '.join(others)}")
    if resources:
        problems.append(f"{label} holds the host's {', '.join(resources)}")
    return problems


def hostdev_problems(vm, pci, usb, wanted_pci, wanted_usb):
    """Why the host's devices pci and usb (get_node_devices) that the VM
    named vm wants (hostdev_users) cannot be given to it: another VM names
    them too, the host has its own network interfaces, disks or graphics
    card on them, or they are USB hubs."""
    problems = []
    for device in pci:
        if device["address"] in wanted_pci:
            problems += device_problems(f"PCI device {device['address']}", device["vms"], device["resources"], vm)
    for device in usb:
        address = (device["bus"], device["device"])
        if any(usb_named(selector, device["model"], address) for selector in wanted_usb):
            label = f"USB device {device['bus']}/{device['device']} ({device['product']})"
            problems += device_problems(label, device["vms"] + device["by_model"], device["resources"], vm)
            if device["hub"]:
                problems.append(f"{label} is a hub")
    return problems


def _pci(name, node, nodes, children, vms):
    cap = node.find("capability")
    address = pci_address(cap.findtext("domain"), cap.findtext("bus"), cap.findtext("slot"), cap.findtext("function"))
    code = int(cap.findtext("class") or "0", 16)
    group = cap.xpath("string(iommuGroup/@number)")
    # SR-IOV: a virtual function's physical one
    physfn = cap.find("capability[@type='phys_function']/address")
    return {
        "address": address,
        "vendor": cap.findtext("vendor") or cap.xpath("string(vendor/@id)"),
        "product": cap.findtext("product") or cap.xpath("string(product/@id)"),
        "ids": f"{cap.xpath('string(vendor/@id)')[2:]}:{cap.xpath('string(product/@id)')[2:]}",
        "kind": PCI_CLASSES.get(code >> 16, _("Other")),
        "driver": node.findtext("driver/name") or "",
        "group": int(group) if group else None,
        "resources": host_resources(name, nodes, children),
        "vms": [vm for vm, pci, _ in vms if address in pci],
        "physfn": pci_address(physfn.get("domain"), physfn.get("bus"), physfn.get("slot"), physfn.get("function"))
        if physfn is not None else "",
        "vfs": len(cap.xpath("capability[@type='virt_functions']/address")),
    }



def _usb(name, node, nodes, children, vms):
    cap = node.find("capability")
    bus, device = int(cap.findtext("bus")), int(cap.findtext("device"))
    model = (cap.xpath("string(vendor/@id)").lower(), cap.xpath("string(product/@id)").lower())
    # a USB device's classes are its interfaces'
    codes = [int(nodes[child].findtext("capability/class") or "0") for child in children.get(name, [])
             if nodes[child].find("capability").get("type") == "usb"]
    named = [(vm, usb_named(selector, model, (bus, device))) for vm, _, selectors in vms for selector in selectors]
    by_address = sorted({vm for vm, how in named if how == "address"})
    return {
        "bus": bus,
        "device": device,
        "vendor": cap.findtext("vendor") or model[0],
        "product": cap.findtext("product") or model[1],
        "model": model,
        "ids": f"{model[0][2:]}:{model[1][2:]}",
        "kinds": sorted({str(USB_CLASSES.get(code, _("Other"))) for code in codes}),
        "hub": USB_HUB in codes,
        "resources": host_resources(name, nodes, children),
        "vms": by_address,
        # VMs that name its model only: which device of the model they take is known only when they start
        "by_model": sorted({vm for vm, how in named if how == "model"} - set(by_address)),
    }


def node_devices(conn):
    """The PCI and USB devices of the host of conn (a wvmConnect), each with what the host has on it
    (host_resources) and the VMs whose definitions name it: one listing
    of every node device, one XML read each (a device gone meanwhile is
    left out), and the VMs' definitions read once (domain_trees)."""
    nodes = {}
    for device in conn.wvm.listAllDevices(0):
        try:
            nodes[device.name()] = etree.fromstring(device.XMLDesc(0))
        except libvirtError as err:
            if err.get_error_code() != VIR_ERR_NO_NODE_DEVICE:
                raise
    children = {}
    for name, node in nodes.items():
        children.setdefault(node.findtext("parent"), []).append(name)

    vms = [(vm, *hostdev_users(trees)) for vm, trees in conn.domain_trees()]
    pci = [_pci(name, node, nodes, children, vms) for name, node in nodes.items()
           if node.find("capability").get("type") == "pci"]
    usb = [_usb(name, node, nodes, children, vms) for name, node in nodes.items()
           if node.find("capability").get("type") == "usb_device"]
    # a model the host has more than one of: a VM that names it by model alone may take any of them
    models = [device["model"] for device in usb]
    for device in usb:
        device["same_model"] = models.count(device["model"]) > 1
    pci.sort(key=lambda device: (device["group"] is None, device["group"] or 0, device["address"]))
    usb.sort(key=lambda device: (device["bus"], device["device"]))
    return pci, usb


def usb_names(conn):
    """The product names of the host's USB devices, by their (vendor, product)
    IDs: one listing of the USB devices, one XML read each; none when they
    cannot be read, as the names are only shown."""
    names = {}
    try:
        for device in conn.wvm.listAllDevices(VIR_CONNECT_LIST_NODE_DEVICES_CAP_USB_DEV):
            cap = etree.fromstring(device.XMLDesc(0)).find("capability")
            model = (cap.xpath("string(vendor/@id)").lower(), cap.xpath("string(product/@id)").lower())
            names[model] = cap.findtext("product") or ""
    except libvirtError:  # a device gone meanwhile, or the host: the IDs are shown
        return {}
    return names


def check_hostdevs(conn, vm, trees):
    """Refuses the host devices the definitions trees give the VM named vm,
    on the host of conn, when they cannot be (hostdev_problems)."""
    wanted = hostdev_users(trees)
    if not any(wanted):
        return
    pci, usb = node_devices(conn)
    if problems := hostdev_problems(vm, pci, usb, *wanted):
        raise util.OperationError("; ".join(problems))
