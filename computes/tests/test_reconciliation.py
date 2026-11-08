from unittest.mock import MagicMock, PropertyMock, patch
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from accounts.models import UserInstance
from computes.models import Compute
from computes.utils import refresh_instance_database
from instances.models import Instance
from computes.tests.fakes import Domain


class InstanceReconciliationTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="test_reconcile_user", password="password")
        self.compute = Compute.objects.create(
            name="reconcile-compute",
            hostname="127.0.0.1",
            login="root",
            password="",
            type=1,
        )

    def test_new_domain_created_in_libvirt_is_added_to_db(self):
        dom1 = Domain(name="vm-alpha", uuid="11111111-1111-1111-1111-111111111111")
        dom2 = Domain(name="vm-beta", uuid="22222222-2222-2222-2222-222222222222")

        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.return_value = [dom1, dom2]
        self.compute.__dict__["proxy"] = mock_proxy
        self.compute.__dict__["status"] = True  # reachable

        refresh_instance_database(self.compute)

        instances = Instance.objects.filter(compute=self.compute).order_by("name")
        self.assertEqual(instances.count(), 2)
        self.assertEqual(instances[0].name, "vm-alpha")
        self.assertEqual(instances[0].uuid, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(instances[1].name, "vm-beta")
        self.assertEqual(instances[1].uuid, "22222222-2222-2222-2222-222222222222")

    def test_domain_deleted_in_libvirt_is_deleted_from_db(self):
        inst = Instance.objects.create(
            compute=self.compute,
            name="vm-to-delete",
            uuid="33333333-3333-3333-3333-333333333333",
        )
        UserInstance.objects.create(instance=inst, user=self.user)

        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.return_value = []
        self.compute.__dict__["proxy"] = mock_proxy
        self.compute.__dict__["status"] = True  # reachable

        refresh_instance_database(self.compute)

        self.assertFalse(Instance.objects.filter(compute=self.compute, uuid="33333333-3333-3333-3333-333333333333").exists())
        self.assertFalse(UserInstance.objects.filter(user=self.user).exists())

    def test_domain_renamed_in_libvirt_preserves_userinstance_and_id(self):
        uuid = "44444444-4444-4444-4444-444444444444"
        inst = Instance.objects.create(
            compute=self.compute,
            name="vm-original-name",
            uuid=uuid,
        )
        original_inst_id = inst.id
        user_inst = UserInstance.objects.create(instance=inst, user=self.user, is_change=True)

        dom_renamed = Domain(name="vm-new-name", uuid=uuid)

        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.return_value = [dom_renamed]
        self.compute.__dict__["proxy"] = mock_proxy
        self.compute.__dict__["status"] = True  # reachable

        refresh_instance_database(self.compute)

        inst.refresh_from_db()
        self.assertEqual(inst.id, original_inst_id)
        self.assertEqual(inst.name, "vm-new-name")
        self.assertEqual(inst.uuid, uuid)

        # Verify UserInstance still exists and still points to the same instance!
        user_inst.refresh_from_db()
        self.assertEqual(user_inst.instance_id, original_inst_id)
        self.assertTrue(user_inst.is_change)

    def test_libvirt_connection_error_leaves_db_untouched(self):
        inst = Instance.objects.create(
            compute=self.compute,
            name="vm-persistent",
            uuid="55555555-5555-5555-5555-555555555555",
        )

        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.side_effect = Exception("Libvirt socket connection refused")
        self.compute.__dict__["proxy"] = mock_proxy
        self.compute.__dict__["status"] = True  # reachable

        refresh_instance_database(self.compute)

        # Instance should NOT be deleted!
        self.assertTrue(Instance.objects.filter(id=inst.id).exists())

    def test_broken_domain_metadata_aborts_sync_safely(self):
        inst = Instance.objects.create(
            compute=self.compute,
            name="vm-persistent-2",
            uuid="66666666-6666-6666-6666-666666666666",
        )

        broken_dom = MagicMock()
        broken_dom.UUIDString.side_effect = Exception("Corrupted domain metadata")

        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.return_value = [broken_dom]
        self.compute.__dict__["proxy"] = mock_proxy
        self.compute.__dict__["status"] = True  # reachable

        refresh_instance_database(self.compute)

        self.assertTrue(Instance.objects.filter(id=inst.id).exists())


class ReconciliationTransactionTestCase(TransactionTestCase):
    """libvirt is asked outside the DB transaction: on SQLite an open transaction
    makes every other write of the app fail while a silent host is waited on."""

    def setUp(self):
        self.compute = Compute.objects.create(name="tx-compute", hostname="127.0.0.1", login="root", password="", type=1)

    def proxy(self, list_domains):
        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.side_effect = list_domains
        self.compute.__dict__["proxy"] = mock_proxy

    def test_libvirt_is_called_outside_the_transaction(self):
        seen = {}

        def status():
            seen["status"] = connection.in_atomic_block
            return True

        def list_domains():
            seen["list"] = connection.in_atomic_block
            return [Domain(name="vm-tx", uuid="77777777-7777-7777-7777-777777777777")]

        self.proxy(list_domains)
        with patch.object(Compute, "status", new_callable=PropertyMock, side_effect=status):
            refresh_instance_database(self.compute)

        self.assertEqual(seen, {"status": False, "list": False})
        self.assertTrue(Instance.objects.filter(compute=self.compute, name="vm-tx").exists())

    def test_a_compute_that_matches_the_database_writes_nothing(self):
        Instance.objects.create(compute=self.compute, name="vm-same", uuid="99999999-9999-9999-9999-999999999999")
        self.proxy(lambda: [Domain(name="vm-same", uuid="99999999-9999-9999-9999-999999999999")])
        self.compute.__dict__["status"] = True
        with CaptureQueriesContext(connection) as queries:
            refresh_instance_database(self.compute)

        self.assertEqual([q["sql"].split()[0] for q in queries.captured_queries], ["SELECT", "SELECT"])

    def test_compute_deleted_while_listing_gets_no_instances(self):
        def list_domains():
            Compute.objects.filter(pk=self.compute.pk).delete()
            return [Domain(name="vm-orphan", uuid="88888888-8888-8888-8888-888888888888")]

        self.proxy(list_domains)
        self.compute.__dict__["status"] = True
        refresh_instance_database(self.compute)

        self.assertFalse(Instance.objects.filter(uuid="88888888-8888-8888-8888-888888888888").exists())
