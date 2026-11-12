"""Fake libvirt hosts, domains and node devices that tests of several
modules share: the migration source and destination, the host devices of
a q35 host, and the IOMMU groups of the PCI passthrough rules."""

from unittest.mock import MagicMock

import libvirt
from lxml import etree

from vrtManager.instance import wvmInstances


def no_domain():
    error = libvirt.libvirtError("Domain not found")
    error.err = (libvirt.VIR_ERR_NO_DOMAIN,)
    return error


class FakeDomain:
    def __init__(self, xml="<domain/>", snapshots=0, saved=False, undefine_fails=False, undefine_lost=False,
                 started=False):
        self.calls = []
        self.xml = xml
        self.snapshots = snapshots
        self.saved = saved
        self.undefine_fails = undefine_fails
        self.undefine_lost = undefine_lost  # undefined, but the reply is lost
        self.started = started  # started by another client during the move
        self.undefined = None
        self.redefined = []
        self.restored_autostart = None

    def migrate(self, dconn, flags, dname, uri, bandwidth):
        self.calls.append((flags, uri))

    def name(self):
        return "vm"

    def UUIDString(self):
        return "u-1"

    inactive_xml = None  # the persistent definition, when it differs

    def XMLDesc(self, flags):
        if flags & libvirt.VIR_DOMAIN_XML_INACTIVE and self.inactive_xml:
            return self.inactive_xml
        return self.xml

    def snapshotNum(self, flags=0):
        return self.snapshots

    def hasManagedSaveImage(self, flags=0):
        return self.saved

    def undefineFlags(self, flags):
        if self.undefine_fails:
            raise libvirt.libvirtError("undefine failed")
        self.undefined = flags
        if self.undefine_lost:
            raise libvirt.libvirtError("Cannot recv data")

    def isPersistent(self):
        return self.undefined is None or bool(self.redefined)

    def isActive(self):
        if not self.started and self.undefined is not None:
            raise no_domain()  # libvirt: an undefined shut-off VM is gone
        return self.started

    def autostart(self):
        return 1

    def setAutostart(self, value):
        self.restored_autostart = value

    def connect(self):
        return self

    def defineXML(self, xml):
        self.redefined.append(xml)
        return self


def no_volume():
    error = libvirt.libvirtError("Storage volume not found")
    error.err = (libvirt.VIR_ERR_NO_STORAGE_VOL,)
    return error


class FakeVolume:
    def __init__(self, backing, pool_type="dir"):
        self.backing = backing
        self.pool_type = pool_type

    def storagePoolLookupByVolume(self):
        return MagicMock(XMLDesc=lambda flags: f"<pool type='{self.pool_type}'/>")

    def XMLDesc(self, flags=0):
        if self.backing is None:
            return "<volume><target><path>x</path></target></volume>"
        return f"<volume><backingStore><path>{self.backing}</path></backingStore></volume>"


class FakePool:
    def __init__(self, host, active=True):
        self.host = host
        self.active = active

    def isActive(self):
        return self.active

    def XMLDesc(self, flags=0):
        return "<pool><target><path>/elsewhere</path></target></pool>"

    def refresh(self, flags=0):
        self.host.refreshes += 1
        self.host.volumes |= self.host.unlisted
        self.host.unlisted = set()

    def storageVolLookupByName(self, name):
        return self.host.storageVolLookupByPath(name)


class FakeHost:
    """The destination's libvirt connection. volumes: the paths its pools
    list; unlisted: files its pools show after a refresh; networks and
    nwfilters: the names of its networks and network filters; secrets: the
    UUID, usage type and usage of each of its secrets."""

    def __init__(self, existing=(), volumes=(), unlisted=(), backing=None, inactive_pools=(), pool_types=None,
                 networks=(), nwfilters=(), secrets=()):
        self.existing = set(existing)
        self.secrets = list(secrets)
        self.networks = list(networks)
        self.nwfilters = list(nwfilters)
        self.defined = []
        self.new = []
        self.volumes = set(volumes)
        self.unlisted = set(unlisted)
        self.backing = backing or {}  # path: the path of its backing file
        self.inactive_pools = set(inactive_pools)
        self.pool_types = pool_types or {}  # path: the type of its volume's pool, dir if not named
        self.refreshes = 0

    def listNetworks(self):
        return self.networks

    def listDefinedNetworks(self):
        return []

    def listNWFilters(self):
        return self.nwfilters

    def listAllSecrets(self, flags=0):
        return [MagicMock(**{"UUIDString.return_value": uuid, "XMLDesc.return_value":
                             f"<secret><usage type='{usage_type}'><name>{usage}</name></usage></secret>"})
                for uuid, usage_type, usage in self.secrets]

    def storageVolLookupByPath(self, path):
        if path not in self.volumes:
            raise no_volume()
        return FakeVolume(self.backing.get(path), self.pool_types.get(path, "dir"))

    def storagePoolLookupByName(self, name):
        return FakePool(self, active=name not in self.inactive_pools)

    def listAllStoragePools(self, flags=0):
        return [FakePool(self)]

    def lookup(self, key):
        if key in self.existing:
            return FakeDomain()
        raise no_domain()

    lookupByName = lookupByUUIDString = lookup

    def defineXML(self, xml):
        self.defined.append(xml)
        self.new.append(FakeDomain())
        return self.new[-1]


class FakeSource:
    def __init__(self, state, nvram=None, **domain):
        self.state = state
        self.nvram = nvram
        self.instance = FakeDomain(**domain)

    def get_nvram(self):
        return self.nvram

    reads = 0

    def get_status(self):
        self.reads += 1
        return self.state

    def get_arch(self):
        return "x86_64"

    def get_dom_emulator(self):
        return "/usr/bin/qemu-system-x86_64"


def destination(host=None):
    dest = wvmInstances.__new__(wvmInstances)
    dest.wvm = host or FakeHost()
    dest.get_emulator = lambda arch: "/usr/bin/qemu-system-x86_64"
    return dest


def with_disks(*disks):
    return "<domain><devices>%s</devices></domain>" % "".join(disks)


def pci(slot, product, code, driver=None, group=None):
    iommu = f"<iommuGroup number='{group}'><address domain='0x0000' bus='0x00' slot='{slot}' function='0x0'/></iommuGroup>" \
        if group is not None else ""
    driver = f"<driver><name>{driver}</name></driver>" if driver else ""
    return (f"pci_0000_00_{int(slot, 16):02x}_0", f"""<device><name>pci_0000_00_{int(slot, 16):02x}_0</name><parent>computer</parent>{driver}
        <capability type='pci'><class>{code}</class><domain>0</domain><bus>0</bus><slot>{int(slot, 16)}</slot><function>0</function>
        <product id='0x1000'>{product}</product><vendor id='0x1af4'>Red Hat, Inc.</vendor>{iommu}</capability></device>""")


def child(name, parent, capability):
    return name, f"<device><name>{name}</name><parent>{parent}</parent>{capability}</device>"


def usb(name, parent, bus, device, product="QEMU Tablet", vendor_id="0x0627", product_id="0x0001"):
    return name, f"""<device><name>{name}</name><parent>{parent}</parent><capability type='usb_device'><bus>{bus}</bus>
        <device>{device}</device><product id='{product_id}'>{product}</product><vendor id='{vendor_id}'>Adomax</vendor>
        </capability></device>"""


def interface(name, parent, code):
    return child(name, parent, f"<capability type='usb'><number>0</number><class>{code}</class></capability>")


NODES = [
    pci("0x06", "Virtio network device", "0x020000", "virtio-pci", group=3),
    child("net_eth0", "pci_0000_00_06_0", "<capability type='net'><interface>eth0</interface></capability>"),
    pci("0x03", "Virtio block device", "0x010000", "virtio-pci", group=2),
    child("virtio1", "pci_0000_00_03_0", "<capability type='system'/>"),  # a level between, not a resource
    child("block_vda", "virtio1", "<capability type='storage'><block>/dev/vda</block></capability>"),
    pci("0x02", "Virtio 1.0 GPU", "0x030000", "virtio-pci", group=2),
    child("drm_card0", "pci_0000_00_02_0", "<devnode type='dev'>/dev/dri/card0</devnode><capability type='drm'><type>primary</type></capability>"),
    child("drm_render", "pci_0000_00_02_0", "<devnode type='dev'>/dev/dri/renderD128</devnode><capability type='drm'><type>render</type></capability>"),
    pci("0x0a", "Ethernet controller", "0x020000", "vfio-pci", group=4),
    pci("0x01", "PIIX3 USB", "0x0c0300", "uhci_hcd"),
    usb("usb_usb1", "pci_0000_00_01_0", 1, 1, "1.1 root hub", "0x1d6b", "0x0001"),
    interface("usb_1_0_1_0", "usb_usb1", 9),
    usb("usb_1_1", "usb_usb1", 1, 2),
    interface("usb_1_1_1_0", "usb_1_1", 3),
    usb("usb_1_2", "usb_usb1", 1, 3),
    interface("usb_1_2_1_0", "usb_1_2", 3),
]


def node(name, xml):
    return MagicMock(**{"name.return_value": name, "XMLDesc.return_value": xml})


BY_MODEL = "<hostdev mode='subsystem' type='usb' managed='yes'><source{auto}><vendor id='0x0627'/><product id='0x0001'/>{address}</source></hostdev>"


def by_model(address="", auto=""):
    return BY_MODEL.format(address=address, auto=auto)


def domain(*devices):
    return f"<domain><name>kiosk-1</name><devices>{''.join(devices)}</devices></domain>"


def device(slot, product, code, driver, group, members=None, bridge=False):
    """A PCI node of an IOMMU test host: a device on bus 0 at slot, in IOMMU group with the slots members (its own by default)."""
    members = members or [slot]
    addresses = "".join(f"<address domain='0x0000' bus='0x00' slot='0x{m:02x}' function='0x0'/>" for m in members)
    driver_xml = f"<driver><name>{driver}</name></driver>" if driver else ""
    bridge_xml = "<capability type='pci-bridge'/>" if bridge else ""
    xml = (f"<device><name>pci_0000_00_{slot:02x}_0</name><parent>computer</parent>{driver_xml}"
           f"<capability type='pci'><class>{code}</class><domain>0</domain><bus>0</bus><slot>{slot}</slot><function>0</function>"
           f"<product id='0x0001'>{product}</product><vendor id='0x8086'>Intel</vendor>{bridge_xml}"
           f"<iommuGroup number='{group}'>{addresses}</iommuGroup></capability></device>")
    return f"pci_0000_00_{slot:02x}_0", etree.fromstring(xml)


IOMMU_NODES = dict([
    device(0x02, "PCIe Root port", "0x060400", "pcieport", 2, bridge=True),
    device(0x03, "SATA controller", "0x010601", "ahci", 7, [0x03, 0x04, 0x05]),
    device(0x04, "SMBus controller", "0x0c0500", "i801_smbus", 7, [0x03, 0x04, 0x05]),
    device(0x05, "LPC controller", "0x060100", "lpc_ich", 7, [0x03, 0x04, 0x05]),  # class 0x06, not a bridge
    device(0x06, "Gigabit NIC", "0x020000", "e1000e", 12),
    device(0x07, "Spare NIC", "0x020000", "vfio-pci", 13),
    device(0x08, "NIC port 0", "0x020000", "vfio-pci", 14, [0x08, 0x09, 0x0a]),
    device(0x09, "NIC port 1", "0x020000", None, 14, [0x08, 0x09, 0x0a]),
    device(0x0a, "Downstream port", "0x060400", "pcieport", 14, [0x08, 0x09, 0x0a], bridge=True),
    device(0x0b, "Accelerator", "0x120000", "vfio-pci", 15, [0x0b, 0x0c]),  # 0x0c cannot be read
    device(0x0d, "GPU", "0x030000", "nouveau", 16, [0x0d, 0x0e]),
    device(0x0e, "GPU audio", "0x040300", "snd_hda_intel", 16, [0x0d, 0x0e]),
])
# what the host has below: a disk on the SATA controller, its interface on the e1000e
IOMMU_NODES["block_sda"] = etree.fromstring("<device><name>block_sda</name><parent>pci_0000_00_03_0</parent>"
                                      "<capability type='storage'><block>/dev/sda</block></capability></device>")
IOMMU_NODES["net_eth1"] = etree.fromstring("<device><name>net_eth1</name><parent>pci_0000_00_06_0</parent>"
                                     "<capability type='net'><interface>eth1</interface></capability></device>")


def vm(name, hostdevs, saved=None):
    """A VM with hostdevs as it runs and, given saved, persistent with those for its next start."""
    def describe(flags=0):
        return f"<domain><devices>{saved if flags else hostdevs}</devices></domain>"
    return MagicMock(**{"name.return_value": name, "XMLDesc.side_effect": describe, "isPersistent.return_value": saved is not None})


PCI_0A = "<hostdev mode='subsystem' type='pci'><source><address domain='0x0000' bus='0x00' slot='0x0a' function='0x0'/></source></hostdev>"


USB_1_3 = "<hostdev mode='subsystem' type='usb'><source><vendor id='0x0627'/><product id='0x0001'/><address bus='1' device='3'/></source></hostdev>"


DUID = "00:01:00:01:2e:8b:3c:41:52:54:00:00:00:40"


def lease(ip, mac=None, expiry=1793265489, hostname=None, clientid=None, family=0):
    return {"iface": "virbr9", "expirytime": expiry, "type": family, "mac": mac, "ipaddr": ip, "prefix": 24,
            "hostname": hostname, "clientid": clientid, "iaid": None}


# a host with a NAT network that hands out addresses (libvirt's test driver node file)
NAT_NETWORK_NODE = """<node>
  <network><name>lab</name><forward mode='nat'/><bridge name='virbr9'/>
    <ip address='192.0.2.1' netmask='255.255.255.0'><dhcp><range start='192.0.2.10' end='192.0.2.20'/>
      <host mac='52:54:00:00:00:31' name='web' ip='192.0.2.31'/></dhcp></ip>
    <ip family='ipv6' address='2001:db8:1::1' prefix='64'><dhcp><host id='0:1:0:1' ip='2001:db8:1::31'/></dhcp></ip>
  </network>
  <network><name>lan</name><forward mode='bridge'/><bridge name='br0'/></network>
  <network><name>direct</name><forward mode='bridge'><interface dev='eth0'/></forward></network>
  <domain type='test'><name>web</name><memory>1024</memory><os><type>hvm</type></os>
    <devices><interface type='network'><source network='lab'/></interface></devices></domain>
</node>"""


CEPH = "8f2c0000-0000-4000-8000-000000000001"
