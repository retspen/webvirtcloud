"""A secret a VM disk or a pool needs is not deleted: without it that VM or
pool no longer starts. A disk or pool names its secret by UUID or by usage.
libvirt's test driver has no secrets, so the connection is a mock."""

from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from vrtManager.util import OperationError
from vrtManager.virtsecrets import wvmSecrets

UUID = "8f2c0000-0000-4000-8000-000000000001"


def libvirt_object(name, xml):
    obj = MagicMock()
    obj.name.return_value = name
    obj.XMLDesc.return_value = xml
    return obj


def disk_vm(name, secret):
    return libvirt_object(name, f"<domain><devices><disk type='network'><source protocol='rbd' name='rbd/{name}'/>"
                                f"<auth username='libvirt'>{secret}</auth><target dev='vdb'/></disk></devices></domain>")


class SecretInUseTests(SimpleTestCase):
    def delete(self, domains=(), pools=()):
        with patch("vrtManager.connection.connection_manager.get_connection") as get:
            wvm = get.return_value
            wvm.listAllDomains.return_value = list(domains)
            wvm.listAllStoragePools.return_value = list(pools)
            secret = wvm.secretLookupByUUIDString.return_value
            secret.usageID.return_value = "client.libvirt secret"
            wvmSecrets("host", "login", "pw", 1).delete_secret(UUID)
        return secret

    def test_a_secret_a_vm_disk_or_a_pool_names_is_not_deleted(self):
        pool = libvirt_object("ceph-rbd", "<pool type='rbd'><source><auth type='ceph' username='libvirt'>"
                                          "<secret usage='client.libvirt secret'/></auth></source></pool>")
        with self.assertRaises(OperationError) as refused:
            self.delete([disk_vm("db-2", f"<secret type='ceph' uuid='{UUID}'/>")], [pool])
        self.assertIn("VMs db-2", str(refused.exception))
        self.assertIn("pools ceph-rbd", str(refused.exception))

    def test_an_unused_secret_is_deleted(self):
        other = disk_vm("web-1", "<secret type='ceph' uuid='8f2c0000-0000-4000-8000-000000000002'/>")
        self.delete([other]).undefine.assert_called_once_with()


class SecretInUsePageTests(TestCase):
    def test_the_page_says_who_needs_it(self):
        compute = Compute.objects.create(name="secret-use", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("secret-use", "su@example.com", "pw"))
        url = reverse("virtsecrets", args=[compute.id])
        with patch("virtsecrets.views.wvmSecrets") as conn:
            conn.return_value.get_secrets.return_value = []
            conn.return_value.delete_secret.side_effect = OperationError(f"Secret {UUID} is used by VMs db-2")
            response = self.client.post(url, {"delete": "", "uuid": UUID})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [f"Secret {UUID} is used by VMs db-2"])
