import base64

from lxml import etree
from vrtManager import util
from vrtManager.connection import wvmConnect

# the element of <usage> that holds the value, per usage type
USAGE_ELEMENTS = {"ceph": "name", "volume": "volume", "iscsi": "target"}


class wvmSecrets(wvmConnect):
    def create_secret(self, ephemeral, private, secret_type, data):
        # built with lxml: data is text, whatever characters it holds
        secret = etree.Element("secret", ephemeral=ephemeral, private=private)
        usage = etree.SubElement(secret, "usage", type=secret_type)
        etree.SubElement(usage, USAGE_ELEMENTS[secret_type]).text = data
        self.wvm.secretDefineXML(etree.tostring(secret, encoding="unicode"))

    def set_secret_value(self, uuid, value):
        """value: the new value as base64 text."""
        secrt = self.get_secret(uuid)
        # validate: a value that is not base64 is refused, not decoded to other bytes
        secrt.setValue(base64.b64decode(value, validate=True))

    def delete_secret(self, uuid):
        """Refused while a VM disk or a pool names it, by UUID or by usage:
        without it that VM or pool would no longer start."""
        secrt = self.get_secret(uuid)
        refs = "//secret[@uuid=$uuid or @usage=$usage]"
        usage = secrt.usageID() or ""
        vms = self.domains_using(lambda domain: domain.xpath(f"devices/disk{refs}", uuid=uuid, usage=usage))
        pools = sorted(pool.name() for pool in self.wvm.listAllStoragePools()
                       if etree.fromstring(pool.XMLDesc(0)).xpath(f"source{refs}", uuid=uuid, usage=usage))
        if vms or pools:
            users = "; ".join(f"{kind} {', '.join(names)}" for kind, names in (("VMs", vms), ("pools", pools)) if names)
            raise util.OperationError(f"Secret {uuid} is used by {users}; remove it from them first")
        secrt.undefine()
