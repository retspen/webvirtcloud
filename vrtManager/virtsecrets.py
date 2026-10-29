import base64

from libvirt import VIR_ERR_NO_STORAGE_POOL, VIR_STORAGE_XML_INACTIVE, libvirtError
from lxml import etree
from vrtManager import util
from vrtManager.connection import wvmConnect

# the element of <usage> that holds the usage, per usage type
USAGE_ELEMENTS = {"ceph": "name", "volume": "volume", "iscsi": "target", "tls": "name", "vtpm": "name"}

# the usage type a reference by usage means: the type the <secret> gives, or
# for a pool's <auth> the auth type; a disk's encryption passphrase is a volume's
REF_USAGE_TYPES = {"ceph": "ceph", "iscsi": "iscsi", "chap": "iscsi", "passphrase": "volume"}


def value_bytes(usage_type, value):
    """The bytes a value typed on the page stands for: a Ceph key as
    `ceph auth get-key` prints it, in base64; any other secret's password or
    passphrase as it is typed."""
    if usage_type != "ceph":
        return value.encode()
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:  # not base64, or not ASCII; the message never holds the value
        raise util.OperationError("A Ceph key is base64 text, as `ceph auth get-key` prints it") from None


def secrets_named(tree, path, by_usage):
    """UUIDs of the secrets the <secret> elements at path name, by UUID or by
    usage; by_usage maps (usage type, usage) to a UUID."""
    uuids = set()
    for ref in tree.xpath(path):
        if ref.get("uuid"):
            uuids.add(ref.get("uuid"))
        else:
            ref_type = ref.get("type") or ref.getparent().get("type")
            uuids.add(by_usage.get((REF_USAGE_TYPES.get(ref_type), ref.get("usage"))))
    return uuids


class wvmSecrets(wvmConnect):
    def pool_trees(self):
        """Each pool's name with its definitions, parsed: the live one, and
        for a persistent pool the one saved for its next start too, read
        whether it is active or not (it may stop meanwhile). A pool gone
        meanwhile is left out."""
        for pool in self.wvm.listAllStoragePools(0):
            try:
                xmls = [pool.XMLDesc(0)]
                if pool.isPersistent():
                    xmls.append(pool.XMLDesc(VIR_STORAGE_XML_INACTIVE))
            except libvirtError as err:
                if err.get_error_code() != VIR_ERR_NO_STORAGE_POOL:
                    raise
                continue
            yield pool.name(), [etree.fromstring(xml) for xml in xmls]

    def get_users(self, secrets):
        """The VMs and pools that name each of secrets (get_secrets_info), by
        UUID: a VM's disks, host devices and vTPM, a pool's source, in any of
        their definitions. Not seen: a LUKS volume's own encryption, the TLS
        settings of qemu.conf, snapshots."""
        by_usage = {(secret["usage_type"], secret["usage"]): secret["uuid"] for secret in secrets}
        users = {}

        def add(kind, name, uuids):
            for uuid in uuids - {None}:
                users.setdefault(uuid, {"vms": [], "pools": []})[kind].append(name)

        for name, trees in self.domain_trees():
            uuids = set()
            for tree in trees:
                uuids.update(secrets_named(tree, "devices//secret", by_usage))
                uuids.update(tree.xpath("devices/tpm/backend/encryption/@secret"))
            add("vms", name, uuids)
        for name, trees in self.pool_trees():
            uuids = set()
            for tree in trees:
                uuids.update(secrets_named(tree, "source//secret", by_usage))
            add("pools", name, uuids)
        return users

    def create_secret(self, usage_type, usage, value="", ephemeral=False, private=False):
        """A secret for usage, with value if one is given: a Ceph key that is
        not base64 defines nothing, and a value libvirt refuses undefines the
        new secret again."""
        value = value_bytes(usage_type, value) if value else None
        # built with lxml: the usage is text, whatever characters it holds
        secret = etree.Element("secret", ephemeral="yes" if ephemeral else "no", private="yes" if private else "no")
        usage_element = etree.SubElement(secret, "usage", type=usage_type)
        etree.SubElement(usage_element, USAGE_ELEMENTS[usage_type]).text = usage
        defined = self.wvm.secretDefineXML(etree.tostring(secret, encoding="unicode"))
        if value is not None:
            try:
                defined.setValue(value)
            except libvirtError:
                defined.undefine()
                raise

    def set_secret_value(self, uuid, value):
        """value as typed on the page; its bytes follow the secret's usage
        type (value_bytes)."""
        secret = self.wvm.secretLookupByUUIDString(uuid)
        usage_type = etree.fromstring(secret.XMLDesc(0)).xpath("string(usage/@type)")
        secret.setValue(value_bytes(usage_type, value))

    def delete_secret(self, uuid):
        """Refused while a VM or a pool names it (get_users): without it that
        VM or pool would no longer start."""
        secret = self.wvm.secretLookupByUUIDString(uuid)
        if users := self.get_users(self.get_secrets_info()).get(uuid):
            named = []
            if users["vms"]:
                named.append(f"VMs {', '.join(users['vms'])}")
            if users["pools"]:
                named.append(f"pools {', '.join(users['pools'])}")
            raise util.OperationError(f"Secret {uuid} is used by {'; '.join(named)}; remove it from them first")
        secret.undefine()
