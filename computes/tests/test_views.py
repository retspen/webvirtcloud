import json
import os
from unittest.mock import patch
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import reverse
from django.test import RequestFactory, TestCase, TransactionTestCase

from vrtManager.connection import CONN_SOCKET, connection_manager
from computes.models import Compute

TEST_COMPUTE_HOST = os.environ.get("TEST_LIBVIRT_HOST", "localhost")
TEST_COMPUTE_LOGIN = os.environ.get("TEST_LIBVIRT_LOGIN", "")
TEST_COMPUTE_PASSWORD = os.environ.get("TEST_LIBVIRT_PASSWORD", "")
TEST_COMPUTE_TYPE = int(os.environ.get("TEST_LIBVIRT_TYPE", CONN_SOCKET))


class ComputesTestCase(TestCase):
    def setUp(self):
        self.client.login(request=RequestFactory().get("/"), username="admin", password="admin")
        self.compute, _ = Compute.objects.get_or_create(
            name="computes-test-compute",
            defaults={
                "hostname": TEST_COMPUTE_HOST,
                "login": TEST_COMPUTE_LOGIN,
                "password": TEST_COMPUTE_PASSWORD,
                "details": "test",
                "type": TEST_COMPUTE_TYPE,
            },
        )

    def tearDown(self):
        Compute.objects.filter(name="computes-test-compute").delete()
        super().tearDown()

    def _require_live_compute(self):
        try:
            conn = connection_manager.get_connection(
                self.compute.hostname,
                self.compute.login,
                self.compute.password,
                self.compute.type,
            )
            if not (conn and conn.isAlive()):
                self.skipTest("Live libvirt compute host not available")
        except Exception:
            self.skipTest("Live libvirt compute host not available")

    def test_index(self):
        response = self.client.get(reverse("computes"))
        self.assertEqual(response.status_code, 200)

    def test_create_update_delete(self):
        response = self.client.get(reverse("add_socket_host"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("add_socket_host"),
            {
                "name": "l1",
                "details": "Created",
                "hostname": "localhost",
                "type": 4,
            },
        )
        self.assertRedirects(response, reverse("computes"))

        compute = Compute.objects.get(name="l1")
        self.assertEqual(compute.name, "l1")
        self.assertEqual(compute.details, "Created")
        created_id = compute.id

        response = self.client.get(reverse("compute_update", args=[created_id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("compute_update", args=[created_id]),
            {
                "name": "l2",
                "details": "Updated",
                "hostname": "localhost",
                "type": 4,
            },
        )
        self.assertRedirects(response, reverse("computes"))

        compute = Compute.objects.get(id=created_id)
        self.assertEqual(compute.name, "l2")
        self.assertEqual(compute.details, "Updated")

        response = self.client.get(reverse("compute_delete", args=[created_id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("compute_delete", args=[created_id]))
        self.assertRedirects(response, reverse("computes"))

        with self.assertRaises(ObjectDoesNotExist):
            Compute.objects.get(id=created_id)

    def test_overview(self):
        self._require_live_compute()
        response = self.client.get(reverse("overview", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_graph(self):
        self._require_live_compute()
        response = self.client.get(reverse("compute_graph", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_instances(self):
        self._require_live_compute()
        response = self.client.get(reverse("instances", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_storages(self):
        self._require_live_compute()
        response = self.client.get(reverse("storages", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_default_storage_volumes(self):
        self._require_live_compute()
        response = self.client.get(
            reverse("volumes", kwargs={"compute_id": self.compute.id, "pool": "default"})
        )
        self.assertEqual(response.status_code, 200)

    def test_default_storage(self):
        self._require_live_compute()
        response = self.client.get(
            reverse("storage", kwargs={"compute_id": self.compute.id, "pool": "default"})
        )
        self.assertEqual(response.status_code, 200)

    def test_networks(self):
        self._require_live_compute()
        response = self.client.get(reverse("networks", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_default_network(self):
        self._require_live_compute()
        response = self.client.get(
            reverse("network", kwargs={"compute_id": self.compute.id, "pool": "default"})
        )
        self.assertEqual(response.status_code, 200)

    def test_interfaces(self):
        self._require_live_compute()
        response = self.client.get(reverse("interfaces", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_nwfilters(self):
        self._require_live_compute()
        response = self.client.get(reverse("nwfilters", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_secrets(self):
        self._require_live_compute()
        response = self.client.get(reverse("virtsecrets", args=[self.compute.id]))
        self.assertEqual(response.status_code, 200)

    def test_machines(self):
        self._require_live_compute()
        response = self.client.get(
            reverse("machines", kwargs={"compute_id": self.compute.id, "arch": "x86_64"})
        )
        self.assertEqual(response.status_code, 200)

    def test_compute_disk_buses(self):
        self._require_live_compute()
        response = self.client.get(
            reverse(
                "buses",
                kwargs={
                    "compute_id": self.compute.id,
                    "arch": "x86_64",
                    "machine": "pc",
                    "disk": "disk",
                },
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_a_disk_is_offered_the_hosts_disk_buses(self):
        with patch("computes.views.wvmConnect") as conn:
            conn.return_value.get_disk_device_types.return_value = ["disk", "cdrom", "lun"]
            conn.return_value.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            response = self.client.get(reverse("buses", args=[self.compute.id, "x86_64", "q35", "disk"]))
        self.assertEqual(json.loads(response.content), {"bus": ["sata", "scsi", "virtio"]})


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
        mock_proxy.wvm.listAllDomains.assert_not_called()

    def _reconcile_compute(self, name, domains):
        from unittest.mock import MagicMock

        compute = Compute.objects.create(name=name, hostname="192.0.2.10", login="test", password="pwd",
                                         type=CONN_SOCKET)
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

        def list_domains():
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
            if len(calls) == 1:
                thread = threading.Thread(target=second_reconcile)
                thread.start()
                thread.join(10)
            return []

        compute = self._reconcile_compute("reconcile-twice-test", list_domains)
        refresh_instance_database(compute)
        self.assertEqual(calls, ["list"])

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


class ComputeInputValidationTestCase(TestCase):
    """hostname and login reach libvirt URIs and ssh unquoted; the form and
    the API reject values that would inject a URI parameter or an ssh option."""

    def test_form_rejects_injecting_hostname(self):
        from computes.forms import SshComputeForm

        form = SshComputeForm(
            data={"name": "c", "hostname": "192.0.2.1/system?command=/evil", "login": "root", "type": 2}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("hostname", form.errors)

    def test_api_rejects_injecting_hostname_and_login(self):
        from computes.api.serializers import ComputeSerializer

        for field, data in (
            ("hostname", {"name": "c", "hostname": "192.0.2.1/system?command=/evil&a=", "login": "root", "type": 2}),
            ("login", {"name": "c", "hostname": "192.0.2.1", "login": "-oProxyCommand=x", "type": 2}),
        ):
            with self.subTest(field=field):
                serializer = ComputeSerializer(data=data)
                self.assertFalse(serializer.is_valid())
                self.assertIn(field, serializer.errors)

    def test_api_accepts_valid_values(self):
        from computes.api.serializers import ComputeSerializer

        serializer = ComputeSerializer(
            data={"name": "c", "hostname": "host.example.com", "login": "root", "type": 2}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_api_accepts_empty_login_for_tcp(self):
        from computes.api.serializers import ComputeSerializer

        serializer = ComputeSerializer(data={"name": "c", "hostname": "192.0.2.1", "login": "", "type": 1})
        self.assertTrue(serializer.is_valid(), serializer.errors)
