from django.utils.translation import gettext_lazy as _
from libvirt import VIR_ERR_NO_NODE_DEVICE, libvirtError
from lxml import etree

from vrtManager.connection import wvmConnect

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


def hostdev_users(trees):
    """What a VM's definitions give it of the host: PCI addresses (of a
    <hostdev>, or of a NIC that is a host device) and USB selectors
    (vendor, product, (bus, device) or None), as libvirt picks a USB device:
    by the parts given, all of them."""
    pci, usb = set(), []
    for tree in trees:
        for address in tree.xpath("devices/hostdev[@mode='subsystem'][@type='pci']/source/address"
                                  " | devices/interface[@type='hostdev']/source/address"
                                  " | devices/interface/actual[@type='hostdev']/source/address"):
            pci.add(pci_address(address.get("domain", "0"), address.get("bus"), address.get("slot"), address.get("function")))
        for source in tree.xpath("devices/hostdev[@mode='subsystem'][@type='usb']/source"):
            address = source.find("address")
            usb.append((source.xpath("string(vendor/@id)").lower(), source.xpath("string(product/@id)").lower(),
                        (int(address.get("bus")), int(address.get("device"))) if address is not None else None))
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


class wvmNodeDevices(wvmConnect):
    def get_node_devices(self):
        """The host's PCI and USB devices, each with what the host has on it
        (host_resources) and the VMs whose definitions name it: one listing
        of every node device, one XML read each (a device gone meanwhile is
        left out), and the VMs' definitions read once (domain_trees)."""
        nodes = {}
        for device in self.wvm.listAllDevices(0):
            try:
                nodes[device.name()] = etree.fromstring(device.XMLDesc(0))
            except libvirtError as err:
                if err.get_error_code() != VIR_ERR_NO_NODE_DEVICE:
                    raise
        children = {}
        for name, node in nodes.items():
            children.setdefault(node.findtext("parent"), []).append(name)

        vms = [(vm, *hostdev_users(trees)) for vm, trees in self.domain_trees()]
        pci = [self._pci(name, node, nodes, children, vms) for name, node in nodes.items()
               if node.find("capability").get("type") == "pci"]
        usb = [self._usb(name, node, nodes, children, vms) for name, node in nodes.items()
               if node.find("capability").get("type") == "usb_device"]
        # a model the host has more than one of: a VM that names it by model alone may take any of them
        models = [device["model"] for device in usb]
        for device in usb:
            device["same_model"] = models.count(device["model"]) > 1
        pci.sort(key=lambda device: (device["group"] is None, device["group"] or 0, device["address"]))
        usb.sort(key=lambda device: (device["bus"], device["device"]))
        return pci, usb

    @staticmethod
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

    @staticmethod
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
            "resources": host_resources(name, nodes, children),
            "vms": by_address,
            # VMs that name its model only: which device of the model they take is known only when they start
            "by_model": sorted({vm for vm, how in named if how == "model"} - set(by_address)),
        }
