import threading
from types import SimpleNamespace

from django.db import connection
from django.test import TransactionTestCase

from computes.utils import libvirt_compute_lock, libvirt_instance_lock
from operations import claims
from vrtManager.connection import CONN_SOCKET
from computes.models import Compute


class OperationLocksTestCase(TransactionTestCase):
    def setUp(self):
        self.compute = SimpleNamespace(pk=987654321)
        self.first = SimpleNamespace(pk=987654321, uuid="wvc-test-uuid-1", compute=self.compute)
        self.second = SimpleNamespace(pk=987654322, uuid="wvc-test-uuid-2", compute=self.compute)

    def test_sibling_vm_can_run_while_same_vm_and_vm_set_changes_are_refused(self):
        acquired = threading.Event()
        release = threading.Event()
        errors = []

        def hold_first_vm():
            try:
                with libvirt_instance_lock(self.first):
                    acquired.set()
                    if not release.wait(10):
                        raise AssertionError("Test did not release the VM lock")
            except Exception as err:
                errors.append(err)
            finally:
                connection.close()

        worker = threading.Thread(target=hold_first_vm)
        worker.start()
        try:
            self.assertTrue(acquired.wait(10))
            with libvirt_instance_lock(self.second):
                pass
            with self.assertRaises(claims.Busy):
                with libvirt_instance_lock(self.first):
                    pass
            with self.assertRaises(claims.Busy):
                with libvirt_compute_lock(self.compute):
                    pass
        finally:
            release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        with libvirt_compute_lock(self.compute):
            pass

    def test_instance_lock_nests_and_cannot_be_upgraded(self):
        with libvirt_instance_lock(self.first):
            with libvirt_instance_lock(self.first):
                pass
            with self.assertRaisesRegex(RuntimeError, "upgrade"):
                with libvirt_compute_lock(self.compute):
                    pass

    def test_compute_exclusive_owner_can_take_an_instance_lock(self):
        with libvirt_compute_lock(self.compute):
            with libvirt_instance_lock(self.first):
                pass


class ComputeConcurrencyTestCase(TransactionTestCase):
    def test_concurrent_refresh_instance_database(self):
        import threading
        from django.db import connection
        from unittest.mock import MagicMock
        from computes.utils import refresh_instance_database
        from instances.models import Instance

        compute = Compute.objects.create(
            name="concurrent-test",
            hostname="127.0.0.1",
            login="test",
            password="pwd",
            type=CONN_SOCKET,
        )

        mock_dom1 = MagicMock()
        mock_dom1.UUIDString.return_value = "11111111-2222-3333-4444-555555555555"
        mock_dom1.name.return_value = "vm-concurrent-1"

        mock_dom2 = MagicMock()
        mock_dom2.UUIDString.return_value = "22222222-3333-4444-5555-666666666666"
        mock_dom2.name.return_value = "vm-concurrent-2"

        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.return_value = [mock_dom1, mock_dom2]
        compute.proxy = mock_proxy
        compute.status = True  # reachable

        exceptions = []

        def worker():
            try:
                refresh_instance_database(compute)
            except Exception as e:
                exceptions.append(e)
            finally:
                connection.close()

        connection.close()
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(exceptions, [])
        self.assertEqual(Instance.objects.filter(compute=compute).count(), 2)

    def test_refresh_skips_a_busy_compute(self):
        from unittest.mock import MagicMock
        from computes.utils import refresh_instance_database
        from instances.models import Instance
        from operations import claims
        from operations.models import Claim

        compute = Compute.objects.create(
            name="lock-busy-test",
            hostname="192.0.2.10",
            login="test",
            password="pwd",
            type=CONN_SOCKET,
        )
        Instance.objects.create(compute=compute, name="wvc-test-existing", uuid="existing-uuid-1234")

        # Libvirt returns an empty list: a refresh that ran would delete the VM
        mock_proxy = MagicMock()
        mock_proxy.wvm.listAllDomains.return_value = []
        compute.proxy = mock_proxy
        compute.status = True

        claims.admit({claims.compute_key(compute.id): Claim.EXCLUSIVE}, holder="other")
        refresh_instance_database(compute)
        self.assertEqual(Instance.objects.filter(compute=compute).count(), 1)
        mock_proxy.wvm.listAllDomains.assert_called_once()  # the pre-check's read; no reconcile

    def _reconcile_compute(self, name, domains):
        """A compute whose database differs from libvirt (a VM libvirt no
        longer lists), so a refresh reconciles it: the listing that domains
        answers second is the one inside the reconcile, the first is the
        pre-check's."""
        from unittest.mock import MagicMock
        from instances.models import Instance

        compute = Compute.objects.create(name=name, hostname="192.0.2.10", login="test", password="pwd",
                                         type=CONN_SOCKET)
        Instance.objects.create(compute=compute, name="wvc-test-gone", uuid="wvc-test-gone-uuid")
        compute.proxy = MagicMock()
        compute.proxy.wvm.listAllDomains.side_effect = domains
        compute.status = True
        return compute

    def test_a_vm_operation_runs_while_a_reconcile_holds_the_compute(self):
        import threading
        from types import SimpleNamespace
        from django.db import connection
        from computes.utils import libvirt_instance_lock, refresh_instance_database

        outcome = []

        def vm_operation():
            try:
                with libvirt_instance_lock(SimpleNamespace(uuid="wvc-test-uuid-1", compute=compute)):
                    outcome.append("ran")
            except Exception as err:
                outcome.append(err)
            finally:
                connection.close()

        calls = []

        def list_domains():
            calls.append("list")
            if len(calls) == 2:  # inside the reconcile
                thread = threading.Thread(target=vm_operation)
                thread.start()
                thread.join(10)
            return []

        compute = self._reconcile_compute("reconcile-shared-test", list_domains)
        refresh_instance_database(compute)
        self.assertEqual(outcome, ["ran"])

    def test_a_second_reconcile_of_the_compute_is_skipped_meanwhile(self):
        """Two reconciles would read libvirt at different times and could
        commit in reverse order, an older listing undoing a newer one."""
        import threading
        from django.db import connection
        from computes.utils import refresh_instance_database

        calls = []

        def second_reconcile():
            try:
                refresh_instance_database(compute)
            finally:
                connection.close()

        def list_domains():
            calls.append("list")
            if len(calls) == 2:  # inside the reconcile
                thread = threading.Thread(target=second_reconcile)
                thread.start()
                thread.join(10)
            return []

        compute = self._reconcile_compute("reconcile-twice-test", list_domains)
        refresh_instance_database(compute)
        # the second one's pre-check, then no listing of its own
        self.assertEqual(calls, ["list", "list", "list"])

    def test_a_reconcile_runs_while_a_job_holds_the_compute_shared(self):
        from computes.utils import refresh_instance_database
        from instances.models import Instance
        from operations import claims
        from operations.models import Claim, Operation

        dom = type("Dom", (), {"UUIDString": lambda self: "33333333-4444-5555-6666-777777777777",
                               "name": lambda self: "wvc-test-vm"})()
        compute = self._reconcile_compute("reconcile-job-test", lambda: [dom])
        op = Operation.objects.create(kind="test.job", username="wvc-test-user", submission_key="key-00000001",
                                      state=Operation.RUNNING)
        Claim.objects.create(operation=op, resource=claims.compute_key(compute.id), mode=Claim.SHARED)
        refresh_instance_database(compute)
        self.assertTrue(Instance.objects.filter(compute=compute, name="wvc-test-vm").exists())

    def test_libvirt_compute_lock_held_by_another_holder_is_busy(self):
        from computes.utils import libvirt_compute_lock
        from operations import claims
        from operations.models import Claim

        compute = Compute.objects.create(
            name="thread-lock-test",
            hostname="192.0.2.10",
            login="test",
            password="pwd",
            type=CONN_SOCKET,
        )
        claims.admit({claims.compute_key(compute.id): Claim.EXCLUSIVE}, holder="other")
        with self.assertRaises(claims.Busy):
            with libvirt_compute_lock(compute):
                pass

    def test_libvirt_compute_lock_reentrant(self):
        from computes.utils import libvirt_compute_lock
        compute = Compute.objects.create(
            name="reentrant-lock-test",
            hostname="192.0.2.10",
            login="test",
            password="pwd",
            type=CONN_SOCKET,
        )
        executed = []
        with libvirt_compute_lock(compute):
            executed.append("outer")
            with libvirt_compute_lock(compute):
                executed.append("inner")
                with libvirt_compute_lock(compute):
                    executed.append("deep")
        self.assertEqual(executed, ["outer", "inner", "deep"])
