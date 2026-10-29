"""A secret a VM or a pool needs is not deleted: without it that VM or pool
no longer starts. A VM names its secret in a disk, a host device or its vTPM,
a pool in its source, by UUID or by usage within the usage type; as they run
and as saved. libvirt's test driver has no secrets, so the connection is a
mock."""

from unittest.mock import MagicMock, patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from vrtManager.util import OperationError
from vrtManager.virtsecrets import wvmSecrets

CEPH = "8f2c0000-0000-4000-8000-000000000001"
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
        with self.assertRaisesRegex(OperationError, f"Secret {CEPH} is used by VMs db-2; pools ceph-rbd"):
            conn.delete_secret(CEPH)
        conn.wvm.secretLookupByUUIDString.return_value.undefine.assert_not_called()

    def test_an_unused_secret_is_deleted(self):
        conn = connection(domains=[vm("web-1", f"<disk><auth><secret type='ceph' uuid='{CEPH}'/></auth></disk>")])
        conn.delete_secret(ISCSI)
        conn.wvm.secretLookupByUUIDString.assert_called_once_with(ISCSI)
        conn.wvm.secretLookupByUUIDString.return_value.undefine.assert_called_once_with()


class SecretInUsePageTests(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="secret-use", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("secret-use", "su@example.com", "pw"))
        self.url = reverse("virtsecrets", args=[compute.id])

    def test_the_page_says_who_needs_it(self):
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.delete_secret.side_effect = OperationError(f"Secret {CEPH} is used by VMs db-2")
            response = self.client.post(self.url, {"delete": "", "uuid": CEPH})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [f"Secret {CEPH} is used by VMs db-2"])

    def test_a_post_to_a_host_not_reached_is_redirected(self):
        with patch("virtsecrets.views.wvmSecrets", side_effect=libvirt.libvirtError("unable to connect")):
            response = self.client.post(self.url, {"delete": "", "uuid": CEPH})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_the_list_is_not_shown_without_its_users(self):
        # it would offer to delete the secrets in use
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.get_secrets_info.return_value = [{"uuid": CEPH, "usage_type": "ceph", "usage": "client.libvirt",
                                                                "ephemeral": False, "private": False}]
            conn.return_value.get_users.side_effect = libvirt.libvirtError("connection reset")
            response = self.client.get(self.url)
        self.assertEqual(response.context["secrets_all"], [])
