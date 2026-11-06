import json
import os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import reverse
from django.test import TestCase

from vrtManager.connection import CONN_SOCKET, connection_manager
from computes.models import Compute
from vrtManager.tests import livetest

TEST_COMPUTE_HOST = os.environ.get("TEST_LIBVIRT_HOST", "localhost")
TEST_COMPUTE_LOGIN = os.environ.get("TEST_LIBVIRT_LOGIN", "")
TEST_COMPUTE_PASSWORD = os.environ.get("TEST_LIBVIRT_PASSWORD", "")
TEST_COMPUTE_TYPE = int(os.environ.get("TEST_LIBVIRT_TYPE", CONN_SOCKET))


class ComputesTestCase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("tests-admin", "admin@example.com", "pw")
        self.client.force_login(self.admin)
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
        if not livetest.enabled():  # never the machine's own libvirt by default
            self.skipTest("Set TEST_LIBVIRT_HOST to run the live libvirt tests")
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

    def _test_pool(self):
        """The suite's own pool on the named test host: a host need not have one called default."""
        self._require_live_compute()
        if not livetest.enabled():
            self.skipTest("TEST_LIBVIRT_HOST is not set")
        conn = connection_manager.get_connection(
            self.compute.hostname, self.compute.login, self.compute.password, self.compute.type
        )
        livetest.ensure_pool(conn)
        self.addCleanup(livetest.remove_pool, conn)
        return livetest.POOL

    def test_storage_volumes(self):
        response = self.client.get(reverse("volumes", kwargs={"compute_id": self.compute.id, "pool": self._test_pool()}))
        self.assertEqual(response.status_code, 200)

    def test_storage(self):
        response = self.client.get(reverse("storage", kwargs={"compute_id": self.compute.id, "pool": self._test_pool()}))
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
        with patch("computes.models.wvmHostDetails") as conn:
            conn.return_value.get_disk_device_types.return_value = ["disk", "cdrom", "lun"]
            conn.return_value.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            response = self.client.get(reverse("buses", args=[self.compute.id, "x86_64", "q35", "disk"]))
        self.assertEqual(json.loads(response.content), {"bus": ["sata", "scsi", "virtio"]})
