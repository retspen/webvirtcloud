"""wvmSecrets: a secret's usage goes into its XML as text; its value is a
Ceph key in base64 or a password as typed, and a value refused leaves no
secret behind; what uses a secret, and deleting one."""

from unittest.mock import MagicMock, patch

import libvirt
from django.test import SimpleTestCase
from lxml import etree

from vrtManager.tests.fakes import CEPH
from vrtManager.util import OperationError
from vrtManager.virtsecrets import wvmSecrets


def connection_and_libvirt():
    with patch("vrtManager.connection.connection_manager.get_connection") as get:
        conn = wvmSecrets("host", "login", "pw", 1)
    return conn, get.return_value


class CreateSecretTests(SimpleTestCase):
    def test_the_usage_is_text_of_its_element(self):
        for usage_type, element, usage in (
            ("volume", "volume", "/var/lib/libvirt/images/vm-1.qcow2"),
            ("iscsi", "target", "iqn.2026-10.test.wvc:lun"),
            ("ceph", "name", "client.libvirt secret"),
            ("tls", "name", "migration"),
            ("vtpm", "name", "VM web-1's vTPM"),
            ("volume", "volume", "/a'b<c>&d\""),
        ):
            with self.subTest(usage_type=usage_type, usage=usage):
                conn, wvm = connection_and_libvirt()
                conn.create_secret(usage_type, usage, private=True)
                secret = etree.fromstring(wvm.secretDefineXML.call_args.args[0])
                self.assertEqual((secret.get("ephemeral"), secret.get("private")), ("no", "yes"))
                self.assertEqual(secret.find("usage").get("type"), usage_type)
                self.assertEqual(secret.findtext(f"usage/{element}"), usage)
                wvm.secretDefineXML.return_value.setValue.assert_not_called()

    def test_a_new_secret_takes_its_value_at_once(self):
        for usage_type, value, stored in (("ceph", "cHcA/w==", b"pw\x00\xff"), ("iscsi", " pass word ", b" pass word ")):
            with self.subTest(usage_type=usage_type):
                conn, wvm = connection_and_libvirt()
                conn.create_secret(usage_type, "lun", value)
                wvm.secretDefineXML.return_value.setValue.assert_called_once_with(stored)

    def test_a_value_refused_leaves_no_secret(self):
        conn, wvm = connection_and_libvirt()
        with self.assertRaisesRegex(OperationError, "base64"):
            conn.create_secret("ceph", "client.libvirt", "not base64!")
        wvm.secretDefineXML.assert_not_called()
        wvm.secretDefineXML.return_value.setValue.side_effect = libvirt.libvirtError("refused")
        with self.assertRaises(libvirt.libvirtError):
            conn.create_secret("iscsi", "lun", "pw")
        wvm.secretDefineXML.return_value.undefine.assert_called_once_with()


class SecretValueTests(SimpleTestCase):
    def set_value(self, usage_type, value):
        conn, wvm = connection_and_libvirt()
        secret = wvm.secretLookupByUUIDString.return_value
        secret.XMLDesc.return_value = f"<secret><usage type='{usage_type}'><name>x</name></usage></secret>"
        conn.set_secret_value("uuid", value)
        return secret.setValue

    def test_a_ceph_key_is_stored_as_its_bytes_a_password_as_typed(self):
        self.set_value("ceph", "cHcA/w==").assert_called_once_with(b"pw\x00\xff")
        # a password that happens to be base64 is not decoded
        self.set_value("iscsi", "cHcA/w==").assert_called_once_with(b"cHcA/w==")
        self.set_value("vtpm", " pässword ").assert_called_once_with(" pässword ".encode())

    def test_a_ceph_key_that_is_not_base64_is_refused_without_the_value(self):
        for value in ("b'cHc='", "not base64!", "kéy"):
            with self.subTest(value=value), self.assertRaises(OperationError) as refused:
                self.set_value("ceph", value)
            self.assertNotIn(value, str(refused.exception))

    def test_an_empty_value_is_refused_in_words(self):
        # libvirt says "value in virSecretSetValue must not be NULL"
        with self.assertRaisesRegex(OperationError, "Type the secret's value"):
            self.set_value("iscsi", "")


ISCSI = "8f2c0000-0000-4000-8000-000000000002"


VTPM = "8f2c0000-0000-4000-8000-000000000003"


def secret(uuid, usage_type, usage):
    return MagicMock(**{"UUIDString.return_value": uuid,
                        "XMLDesc.return_value": f"<secret><usage type='{usage_type}'><name>{usage}</name></usage></secret>"})


def owner(name, xml, saved=None, active=False, persistent=True):
    """A domain or a pool: xml as it runs, saved as defined for its next start."""
    return MagicMock(**{"name.return_value": name, "XMLDesc.side_effect": lambda flags=0: (saved or xml) if flags else xml,
                        "isActive.return_value": active, "isPersistent.return_value": persistent})


def vm(name, devices, **kwargs):
    return owner(name, f"<domain><devices>{devices}</devices></domain>", **kwargs)


def pool(name, auth, **kwargs):
    return owner(name, f"<pool type='rbd'><source>{auth}</source></pool>", **kwargs)


def gone(code):
    err = libvirt.libvirtError("gone")
    err.get_error_code = lambda: code
    return MagicMock(**{"name.return_value": "gone", "XMLDesc.side_effect": err})


# the same usage, of two types: a reference by usage names the one of its type
SECRETS = [secret(CEPH, "ceph", "client.libvirt"), secret(ISCSI, "iscsi", "client.libvirt"), secret(VTPM, "vtpm", "tpm")]


def connection(domains=(), pools=(), secrets=SECRETS):
    with patch("vrtManager.connection.connection_manager.get_connection") as get:
        conn = wvmSecrets("host", "login", "pw", 1)
    get.return_value.configure_mock(**{"listAllDomains.return_value": list(domains),
                                       "listAllStoragePools.return_value": list(pools),
                                       "listAllSecrets.return_value": list(secrets)})
    return conn


def users(**kwargs):
    conn = connection(**kwargs)
    return conn.get_users(conn.get_secrets_info())


class UsersTests(SimpleTestCase):
    def test_vms_name_secrets_in_disks_host_devices_and_vtpm(self):
        found = users(domains=[
            vm("rbd-1", f"<disk type='network'><auth username='libvirt'><secret type='ceph' uuid='{CEPH}'/></auth></disk>"),
            vm("lun-1", "<hostdev mode='subsystem' type='scsi'><source protocol='iscsi'><auth username='u'>"
                        "<secret type='iscsi' usage='client.libvirt'/></auth></source></hostdev>"),
            vm("tpm-1", f"<tpm model='tpm-crb'><backend type='emulator'><encryption secret='{VTPM}'/></backend></tpm>"),
        ])
        self.assertEqual(found, {CEPH: {"vms": ["rbd-1"], "pools": []}, ISCSI: {"vms": ["lun-1"], "pools": []},
                                 VTPM: {"vms": ["tpm-1"], "pools": []}})

    def test_a_pool_names_its_secret_by_the_auth_type_and_as_saved(self):
        found = users(pools=[
            pool("ceph-rbd", "<auth type='ceph' username='libvirt'><secret usage='client.libvirt'/></auth>"),
            # chap is iSCSI; named only for its next start
            pool("lun", "", saved="<pool><source><auth type='chap' username='u'><secret usage='client.libvirt'/>"
                                  "</auth></source></pool>", active=False),
        ])
        self.assertEqual(found, {CEPH: {"vms": [], "pools": ["ceph-rbd"]}, ISCSI: {"vms": [], "pools": ["lun"]}})

    def test_a_vm_uses_a_secret_as_it_runs_and_as_saved(self):
        disk = "<disk><auth username='libvirt'><secret type='ceph' usage='client.libvirt'/></auth></disk>"
        # saved only: read whether it runs or not, as it may stop between the reads
        for kwargs in ({"active": True, "saved": f"<domain><devices>{disk}</devices></domain>"},
                       {"active": False, "saved": f"<domain><devices>{disk}</devices></domain>"},
                       {"active": False}, {"active": True, "persistent": False}):
            devices = "" if "saved" in kwargs else disk
            with self.subTest(**kwargs):
                self.assertEqual(users(domains=[vm("db-1", devices, **kwargs)]), {CEPH: {"vms": ["db-1"], "pools": []}})

    def test_what_is_gone_meanwhile_is_left_out_other_errors_are_raised(self):
        found = users(domains=[gone(libvirt.VIR_ERR_NO_DOMAIN)], pools=[gone(libvirt.VIR_ERR_NO_STORAGE_POOL)],
                      secrets=[gone(libvirt.VIR_ERR_NO_SECRET)])
        self.assertEqual(found, {})
        with self.assertRaises(libvirt.libvirtError):
            users(domains=[gone(libvirt.VIR_ERR_OPERATION_FAILED)])


class NoValueReadTests(SimpleTestCase):
    def test_the_list_and_its_users_read_no_value(self):
        for listed in SECRETS:
            listed.value.side_effect = AssertionError("a secret's value was read")
        conn = connection(domains=[vm("db-1", f"<disk><auth><secret type='ceph' uuid='{CEPH}'/></auth></disk>")])
        conn.get_users(conn.get_secrets_info())
        conn.wvm.secretLookupByUUIDString.assert_not_called()


class DeleteTests(SimpleTestCase):
    def test_a_secret_a_vm_or_a_pool_names_is_not_deleted(self):
        conn = connection(domains=[vm("db-2", f"<disk><auth><secret type='ceph' uuid='{CEPH}'/></auth></disk>")],
                          pools=[pool("ceph-rbd", "<auth type='ceph'><secret usage='client.libvirt'/></auth>")])
        conn.wvm.secretLookupByUUIDString.return_value.UUIDString.return_value = CEPH
        with self.assertRaisesRegex(OperationError, f"Secret {CEPH} is used by VMs db-2; pools ceph-rbd"):
            conn.delete_secret(CEPH)
        conn.wvm.secretLookupByUUIDString.return_value.undefine.assert_not_called()

    def test_a_secret_in_use_named_in_capitals_is_not_deleted(self):
        # libvirt finds it by the UUID in capitals, its users name it in small letters
        conn = connection(domains=[vm("db-2", f"<disk><auth><secret type='ceph' uuid='{CEPH}'/></auth></disk>")])
        conn.wvm.secretLookupByUUIDString.return_value.UUIDString.return_value = CEPH
        with self.assertRaisesRegex(OperationError, "is used by VMs db-2"):
            conn.delete_secret(CEPH.upper())
        conn.wvm.secretLookupByUUIDString.return_value.undefine.assert_not_called()

    def test_an_unused_secret_is_deleted(self):
        conn = connection(domains=[vm("web-1", f"<disk><auth><secret type='ceph' uuid='{CEPH}'/></auth></disk>")])
        conn.delete_secret(ISCSI)
        conn.wvm.secretLookupByUUIDString.assert_called_once_with(ISCSI)
        conn.wvm.secretLookupByUUIDString.return_value.undefine.assert_called_once_with()
