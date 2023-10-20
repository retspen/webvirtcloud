import random
import secrets
import re
import string

import libvirt
import lxml.etree as etree

from django.conf import UserSettingsHolder, settings


def is_kvm_available(xml):
    kvm_domains = get_xml_path(xml, "//domain/@type='kvm'")
    return kvm_domains > 0


def randomMAC():
    """Generate a random MAC address."""
    # qemu MAC
    mac = settings.MAC_OUI + ":%02x:%02x:%02x" % (
        random.randint(0x00, 0xFF),
        random.randint(0x00, 0xFF),
        random.randint(0x00, 0xFF),
    )
    return mac


def randomUUID():
    """Generate a random UUID."""
    u = [secrets.randbelow(256) for _ in range(16)]
    u[6] = u[6] & 15 | 4 << 4
    u[8] = u[8] & 63 | 2 << 6
    return "-".join(["%02x" * 4, "%02x" * 2, "%02x" * 2, "%02x" * 2, "%02x" * 6]) % tuple(u)


def randomPasswd(length=12, alphabet=string.ascii_letters + string.digits):
    """Generate a random password"""
    return "".join([secrets.choice(alphabet) for _ in range(length)])


def get_max_vcpus(conn, guest_type=None):
    """@param conn: libvirt connection to poll for max possible vcpus
    @param guest_type: optional guest type (kvm, etc.)"""
    if type is None:
        guest_type = conn.getType()
    try:
        m = conn.getMaxVcpus(guest_type.lower())
    except libvirt.libvirtError:
        m = 32
    return m


def xml_escape(xml_str):
    """Replaces chars ' " < > & with xml safe counterparts"""
    if xml_str is None:
        return None

    xml_str = xml_str.replace("&", "&amp;")
    xml_str = xml_str.replace("'", "&apos;")
    xml_str = xml_str.replace('"', "&quot;")
    xml_str = xml_str.replace("<", "&lt;")
    xml_str = xml_str.replace(">", "&gt;")
    return xml_str


def compareMAC(p, q):
    """Compare two MAC addresses"""
    pa = p.split(":")
    qa = q.split(":")

    if len(pa) != len(qa):
        if p > q:
            return 1
        else:
            return -1

    for i in range(len(pa)):
        n = int(pa[i], 0x10) - int(qa[i], 0x10)
        if n > 0:
            return 1
        elif n < 0:
            return -1
    return 0


def get_xml_path(xml, path=None, func=None):
    """
    Return the content from the passed xml xpath, or return the result
    of a passed function (receives xpathContext as its only arg)
    """
    doc = None
    result = None

    doc = etree.fromstring(xml)
    if path:
        result = get_xpath(doc, path)
    elif func:
        result = func(doc)

    else:
        raise ValueError("'path' or 'func' is required.")
    return result


def get_xpath(doc, path):
    result = None

    ret = doc.xpath(path)
    if ret is not None:
        if isinstance(ret, list):
            if len(ret) >= 1:
                result = ret[0].text if hasattr(ret[0], "text") else ret[0]
        else:
            result = ret

    return result


def pretty_mem(val):
    val = int(val)
    if val > (10 * 1024 * 1024):
        return "%2.2f GB" % (val / (1024.0 * 1024.0))
    else:
        return "%2.0f MB" % (val / 1024.0)


def pretty_bytes(val):
    val = int(val)
    if val > (1024 * 1024 * 1024):
        return "%2.2f GB" % (val / (1024.0 * 1024.0 * 1024.0))
    else:
        return "%2.2f MB" % (val / (1024.0 * 1024.0))


def validate_uuid(val):
    if not isinstance(val, str):
        raise ValueError("UUID must be a string.")

    form = re.match("[a-fA-F0-9]{8}[-]([a-fA-F0-9]{4}[-]){3}[a-fA-F0-9]{12}$", val)
    if form is None:
        form = re.match("[a-fA-F0-9]{32}$", val)
        if form is None:
            raise ValueError(
                "UUID must be a 32-digit hexadecimal number. It may take "
                "the form xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx or may "
                "omit hyphens altogether."
            )

        else:  # UUID had no dashes, so add them in
            val = val[0:8] + "-" + val[8:12] + "-" + val[12:16] + "-" + val[16:20] + "-" + val[20:32]
    return val


def validate_macaddr(val):
    if val is None:
        return

    if not (isinstance(val, str) or isinstance(val, str)):
        raise ValueError("MAC address must be a string.")

    form = re.match("^([0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2}$", val)
    if form is None:
        raise ValueError("MAC address must be of the format AA:BB:CC:DD:EE:FF, was {}".format(val))


# Mapping of UEFI binary names to their associated architectures. We
# only use this info to do things automagically for the user, it shouldn't
# validate anything the user explicitly enters.
UEFI_ARCH_PATTERNS = {
    "i686": [
        r".*ovmf-ia32.*",  # fedora, gerd's firmware repo
    ],
    "x86_64": [
        r".*OVMF_CODE\.fd",  # RHEL
        r".*ovmf-x64/OVMF.*\.fd",  # gerd's firmware repo
        r".*ovmf-x86_64-.*",  # SUSE
        r".*ovmf.*",
        ".*OVMF.*",  # generic attempt at a catchall
    ],
    "aarch64": [
        r".*AAVMF_CODE\.fd",  # RHEL
        r".*aarch64/QEMU_EFI.*",  # gerd's firmware repo
        r".*aarch64.*",  # generic attempt at a catchall
    ],
    "armv7l": [
        r".*arm/QEMU_EFI.*",  # fedora, gerd's firmware repo
    ],
}


def vol_dev_type(vol_bus):
    if vol_bus == "ide":
        return "hd"
    elif vol_bus == "fdc":
        return "fd"
    elif vol_bus == "virtio":
        return "vd"
    elif vol_bus in ["scsi", "sata"]:
        return "sd"

