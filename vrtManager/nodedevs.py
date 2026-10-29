from django.utils.translation import gettext_lazy as _
from libvirt import (VIR_CONNECT_LIST_NODE_DEVICES_CAP_PCI_DEV, VIR_CONNECT_LIST_NODE_DEVICES_CAP_USB_DEV,
                     VIR_ERR_NO_NODE_DEVICE, libvirtError)
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


def usb_hub(name, nodes, children):
    """True when the USB device named name is a hub (an interface of class 9)."""
    return any(nodes[child].findtext("capability/class") == str(USB_HUB) for child in children.get(name, [])
               if nodes[child].find("capability").get("type") == "usb")


def host_resources(name, nodes, children):
    """What the host itself has on the device named name or below it: its
    network interfaces, block devices, graphics cards and USB devices (a
    keyboard, or one given to a VM), by name. Giving the device to a VM
    takes them from the host."""
    found = []
    for child in children.get(name, []):
        cap = nodes[child].find("capability")
        if cap.get("type") == "net":
            found.append(cap.findtext("interface"))
        elif cap.get("type") == "storage":
            found.append(cap.findtext("block"))
        elif cap.get("type") == "drm" and cap.findtext("type") == "primary":
            found.append(nodes[child].xpath("string(devnode[@type='dev'])"))
        elif cap.get("type") == "usb_device" and not usb_hub(child, nodes, children):
            found.append(f"USB device {cap.findtext('bus')}/{cap.findtext('device')} ({cap.findtext('product')})")
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


def managed_pci(tree):
    """The PCI addresses a VM's definition gives it as managed host devices:
    libvirt takes them from their host drivers when the VM starts."""
    return {pci_address(a.get("domain", "0"), a.get("bus"), a.get("slot"), a.get("function"))
            for a in tree.xpath("devices/hostdev[@mode='subsystem'][@type='pci'][@managed='yes']/source/address")}


def pci_problems(vm, device, by_address, managed):
    """Why the host's PCI device (get_node_devices) cannot be given to the VM
    named vm, whose definition gives it the managed PCI devices at the
    addresses managed: by_address holds every PCI device of the host. Its
    IOMMU group goes to the VM as a whole, so each other endpoint in it must
    be one of managed, or have no driver or vfio-pci; no other VM may have
    any of them; bridges stay with the pcieport driver or none. Nothing in
    the group is taken implicitly."""
    label = f"PCI device {device['address']}"
    # a bridge of any kind (a host bridge, a PCIe port) is the host's
    if device["bridge"] or device["bridge_class"]:
        return [f"{label} is a bridge"]
    problems = device_problems(label, device["vms"], device["resources"], vm)
    if device["resources"]:
        problems.append(f"bind {device['address']} to vfio-pci on the host first if it is not needed there")
    if device["group"] is None:
        return problems + [f"{label} is in no IOMMU group"]
    shares = f"{label} shares IOMMU group {device['group']} with"
    for member in device["group_members"]:
        if member == device["address"]:
            continue
        other = by_address.get(member)
        if other is None:
            problems.append(f"{shares} {member}, which cannot be read")
        elif others := sorted(set(other["vms"]) - {vm}):
            problems.append(f"{shares} {member} ({other['product']}), which {', '.join(others)} uses")
        elif other["bridge"]:
            if other["driver"] not in ("", "pcieport"):
                problems.append(f"{shares} the bridge {member} (driver {other['driver']})")
        elif member not in managed and other["driver"] not in ("", "vfio-pci"):
            problems.append(f"{shares} {member} ({other['product']}), which the host (driver {other['driver']}) uses")
    return problems


def hostdev_problems(vm, pci, usb, wanted_pci, wanted_usb, managed=frozenset()):
    """Why the host's devices pci and usb (get_node_devices) that a definition
    of the VM named vm wants (hostdev_users; managed_pci) cannot be given to
    it: a PCI device the host does not have, pci_problems; for USB ones,
    another VM names them or their PCI controller too, the host has its own
    network interfaces or disks on them, or they are hubs."""
    by_address = {device["address"]: device for device in pci}
    problems = [f"PCI device {address} is not on the host" for address in sorted(wanted_pci - by_address.keys())]
    for device in pci:
        if device["address"] in wanted_pci:
            problems += pci_problems(vm, device, by_address, managed)
    for device in usb:
        address = (device["bus"], device["device"])
        if any(usb_named(selector, device["model"], address) for selector in wanted_usb):
            label = f"USB device {device['bus']}/{device['device']} ({device['product']})"
            problems += device_problems(label, device["vms"] + device["by_model"], device["resources"], vm)
            if device["hub"]:
                problems.append(f"{label} is a hub")
            controller = by_address.get(device["controller"])
            if controller and (holders := sorted(set(controller["vms"]) - {vm})):
                problems.append(f"{label} is on the PCI controller {controller['address']}, given to {', '.join(holders)}")
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
        "group_members": [pci_address(a.get("domain"), a.get("bus"), a.get("slot"), a.get("function"))
                          for a in cap.xpath("iommuGroup/address")],
        # a bridge header (a PCIe port too), as against class 0x06 functions such as an LPC controller
        "bridge": cap.find("capability[@type='pci-bridge']") is not None
        or cap.find("capability[@type='cardbus-bridge']") is not None or node.findtext("driver/name") == "pcieport",
        # of the bridge class: a host bridge or an LPC controller too
        "bridge_class": code >> 16 == 0x06,
        "resources": host_resources(name, nodes, children),
        "vms": [vm for vm, pci, usb_selectors in vms if address in pci],
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
    # the PCI controller it is on: a VM given that controller takes it too
    parent = node.findtext("parent")
    while parent in nodes and nodes[parent].find("capability").get("type") != "pci":
        parent = nodes[parent].findtext("parent")
    controller = nodes[parent].find("capability") if parent in nodes else None
    named = [(vm, usb_named(selector, model, (bus, device))) for vm, pci_addresses, selectors in vms for selector in selectors]
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
        "controller": pci_address(controller.findtext("domain"), controller.findtext("bus"), controller.findtext("slot"),
                                  controller.findtext("function")) if controller is not None else "",
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


def device_names(conn):
    """The product names of the host's USB devices, by their (vendor,
    product) IDs, and of its PCI devices, by address: one listing of each,
    one XML read per device; none when they cannot be read, as the names
    are only shown."""
    names = {}
    try:
        for flag in (VIR_CONNECT_LIST_NODE_DEVICES_CAP_USB_DEV, VIR_CONNECT_LIST_NODE_DEVICES_CAP_PCI_DEV):
            for device in conn.wvm.listAllDevices(flag):
                cap = etree.fromstring(device.XMLDesc(0)).find("capability")
                if cap.get("type") == "pci":
                    key = pci_address(cap.findtext("domain"), cap.findtext("bus"), cap.findtext("slot"), cap.findtext("function"))
                else:
                    key = (cap.xpath("string(vendor/@id)").lower(), cap.xpath("string(product/@id)").lower())
                names[key] = cap.findtext("product") or ""
    except libvirtError:  # a device gone meanwhile, or the host: the IDs and addresses are shown
        return {}
    return names


def check_hostdevs(conn, vm, trees):
    """Refuses the host devices the definitions trees give the VM named vm,
    on the host of conn, when they cannot be (hostdev_problems): each
    definition on its own, as the VM starts from one of them."""
    wanted = [(tree, hostdev_users([tree])) for tree in trees]
    if not any(pci or usb for tree, (pci, usb) in wanted):
        return
    pci, usb = node_devices(conn)
    problems = []
    for tree, (wanted_pci, wanted_usb) in wanted:
        problems += hostdev_problems(vm, pci, usb, wanted_pci, wanted_usb, managed_pci(tree))
    if problems:
        raise util.OperationError("; ".join(dict.fromkeys(problems)))
