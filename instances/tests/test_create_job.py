"""VM create runs as a job, from the page and from the API."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import libvirt

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from appsettings.settings import get_settings
from computes.models import Compute
from instances.jobs import CreateInstance
from instances.models import Instance
from operations.jobs import Context
from operations.models import Operation, acquire

BODY = {"name": "api-vm", "vcpu": 1, "vcpu_mode": "host-model", "memory": 512, "networks": "default", "mac": "",
        "nwfilter": "", "storage": "default", "hdd_size": 1, "cache_mode": "none", "meta_prealloc": False,
        "virtio": True, "qemu_ga": True, "video": "vga", "listener_addr": "0.0.0.0", "submission_key": "key-api00001"}


class CreateJobTestCase(TransactionTestCase):
    def setUp(self):
        get_settings()
        admin = get_user_model().objects.create_superuser("create_admin", "a@example.com", "pw")
        self.client.force_login(admin)
        self.compute = Compute.objects.create(name="create-c", hostname="192.0.2.40", login="root", password="", type=1)
        patcher = patch("instances.jobs.wvmCreate")
        self.conn = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.conn.get_instances.return_value = []
        self.conn.get_cache_modes.return_value = {"none": "Disable cache"}
        self.conn.get_disk_bus_types.return_value = ["virtio", "sata"]
        self.conn.create_volume.return_value = "/srv/default/api-vm.qcow2"

    def test_the_api_queues_the_create_and_the_worker_defines_and_records_it(self):
        url = f"/api/v1/computes/{self.compute.pk}/instances/create/x86_64/q35/"
        response = self.client.post(url, BODY, content_type="application/json")
        self.assertEqual(response.status_code, 202)
        op = Operation.objects.get()
        self.assertEqual(response["Location"], f"/api/v1/operations/{op.pk}/")
        self.conn.create_instance.assert_not_called()

        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        CreateInstance().run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
        self.assertEqual(self.conn.create_instance.call_args.kwargs["uuid"], op.intent["uuid"])
        self.assertTrue(Instance.objects.filter(uuid=op.intent["uuid"], name="api-vm").exists())

    def test_a_refused_create_queues_nothing(self):
        url = f"/api/v1/computes/{self.compute.pk}/instances/create/x86_64/q35/"
        response = self.client.post(url, {**BODY, "cache_mode": "writeback"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Operation.objects.exists())

    def test_impossible_sizes_are_refused_by_the_api(self):
        url = f"/api/v1/computes/{self.compute.pk}/instances/create/x86_64/q35/"
        for field, value in (("vcpu", 0), ("memory", -512), ("hdd_size", 0)):
            with self.subTest(field=field):
                response = self.client.post(url, {**BODY, field: value, "submission_key": f"key-min-{field}"},
                                            content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertFalse(Operation.objects.exists())

    def test_a_resubmitted_key_with_other_fields_is_a_conflict(self):
        url = f"/api/v1/computes/{self.compute.pk}/instances/create/x86_64/q35/"
        self.client.post(url, BODY, content_type="application/json")
        response = self.client.post(url, {**BODY, "memory": 1024}, content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Operation.objects.count(), 1)

    @patch("instances.jobs.wvmConnect")
    def test_a_create_that_left_nothing_failed(self, conn):
        op = Operation(params={**BODY, "template": ""},
                       intent={"compute": self.compute.pk, "uuid": "abababab-0000-1111-2222-333333333333",
                               "name": "api-vm"})
        missing = libvirt.libvirtError("no domain")
        missing.err = (libvirt.VIR_ERR_NO_DOMAIN, libvirt.VIR_FROM_QEMU, "no domain")
        conn.return_value.wvm.lookupByUUIDString.side_effect = missing
        pool = MagicMock()
        pool.listVolumes.return_value = ["other.qcow2"]
        conn.return_value.wvm.listAllStoragePools.return_value = [pool]
        self.assertEqual(CreateInstance().reconcile(op).state, Operation.FAILED)
        pool.listVolumes.return_value = ["api-vm.qcow2"]
        self.assertEqual(CreateInstance().reconcile(op).state, Operation.UNCERTAIN)
