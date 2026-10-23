"""Changes to storage pools and volumes, and the volume jobs, write rows on the Logs page."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TransactionTestCase
from django.urls import reverse

from computes.models import Compute
from logs.models import Logs
from operations import claims, jobs
from operations.jobs import Context, Outcome
from operations.models import Claim, Operation, acquire
from storages.jobs import CloneVolume
from storages.tests import test_upload_job as upload_tests
from storages.upload import write_chunk


def rows():
    return list(Logs.objects.order_by("id").values_list("message", "success"))


class CloneRowTests(TransactionTestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c1", hostname="192.0.2.20", login="root", password="", type=1)
        self.admin = get_user_model().objects.create_superuser("audit-admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()  # the login's row
        patcher = patch("storages.jobs.wvmStorage")
        self.stg = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.stg.get_volumes.return_value = ["base.qcow2"]
        self.stg.get_volume_format_type.return_value = "qcow2"
        self.stg.clone_name.return_value = "copy.qcow2"
        self.stg.clone_volume.return_value = "copy.qcow2"
        page = patch("storages.views.wvmStorage")
        conn = page.start().return_value
        conn.is_active.return_value = False
        conn.get_size.return_value = (1, 1)
        self.addCleanup(page.stop)
        self.url = reverse("storage", args=[self.compute.pk, "default"])

    def submit(self, key):
        self.client.post(self.url, {"cln_volume": "1", "image": "base.qcow2", "name": "copy", "submission_key": key})
        return Operation.objects.get(submission_key=key)

    def run_and_finish(self, op, outcome):
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        CloneVolume().run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
        jobs.finish(op, outcome)

    def test_a_clone_writes_its_row_when_it_ends(self):
        op = self.submit("key-vol00001")
        self.assertEqual(rows(), [])
        self.run_and_finish(op, Outcome(Operation.SUCCEEDED))
        self.assertEqual(rows(), [("Storage pool default: clone volume base.qcow2 as copy.qcow2", True)])
        self.assertEqual(Logs.objects.get().host, "c1")

        self.run_and_finish(self.submit("key-vol00002"), Outcome(Operation.FAILED, error="disk full"))
        jobs.cancel(self.submit("key-vol00003").pk, self.admin)
        self.assertEqual(rows()[1:], [
            ("Storage pool default: clone volume base.qcow2 as copy.qcow2 (failed)", False),
            ("Storage pool default: clone volume base.qcow2 as copy.qcow2 (cancelled)", None),
        ])

    def test_a_refused_clone_is_a_failed_row(self):
        self.stg.get_volumes.return_value = ["base.qcow2", "copy.qcow2"]
        self.client.post(self.url, {"cln_volume": "1", "image": "base.qcow2", "name": "copy",
                                    "submission_key": "key-vol00004"})
        self.assertFalse(Operation.objects.exists())
        self.assertEqual(rows(), [
            ("Storage pool default: clone volume base.qcow2 as copy: Name of volume already in use", False)])

    def test_a_busy_pool_refuses_the_clone(self):
        self.stg.get_volumes.return_value = ["base.qcow2"]
        claims.admit({claims.pool_key(self.compute.pk, "default"): Claim.EXCLUSIVE}, holder="192.0.2.30:1:1")
        self.client.post(self.url, {"cln_volume": "1", "image": "base.qcow2", "name": "copy",
                                    "submission_key": "key-vol00005"})
        [(message, success)] = rows()
        self.assertFalse(success)
        self.assertTrue(message.startswith("Storage pool default: clone volume base.qcow2 as copy: "), message)


class UploadRowTests(upload_tests.LocalPool, upload_tests.UploadTestCase):
    def request(self):
        request = RequestFactory().post("/")
        request.user = self.admin
        SessionMiddleware(lambda r: None).process_request(request)
        return request

    def chunk(self, index, data, name=" disk.iso", total=2, size=6):
        return write_chunk(self.admin, self.conn, self.compute, "default", upload_tests.KEY,
                           {"name": name, "size": size, "chunks": total}, index, SimpleUploadedFile("chunk", data),
                           request=self.request())

    def test_an_upload_writes_one_row(self):
        self.chunk(0, b"abc")
        self.chunk(0, b"abc")  # a retried first chunk
        self.assertEqual(rows(), [])
        self.chunk(1, b"def")
        self.chunk(1, b"def")  # the answer to the last chunk was lost
        self.assertEqual(rows(), [("Storage pool default: upload volume disk.iso", True)])
        self.assertEqual(Logs.objects.get().host, "up-c")

    def test_a_refused_upload_is_a_failed_row(self):
        open(self.path(), "wb").close()
        with self.assertRaises(FileExistsError):
            self.chunk(0, b"abc")
        self.assertEqual(rows(), [("Storage pool default: upload volume disk.iso: FileExistsError", False)])


class PoolAndVolumeRowTests(TransactionTestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c1", hostname="192.0.2.21", login="root", password="", type=1)
        self.admin = get_user_model().objects.create_superuser("audit-admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()  # the login's row
        for name, target in (("pool", "storages.views.wvmStorage"), ("pools", "storages.views.wvmStorages"),
                             ("api_pool", "storages.api.viewsets.wvmStorage")):
            patcher = patch(target)
            conn = patcher.start().return_value
            self.addCleanup(patcher.stop)
            conn.is_active.return_value = True
            conn.get_size.return_value = (1, 1)
            conn.get_storages_info.return_value = []
            conn.get_storages.return_value = ["default"]
            conn.get_secrets.return_value = []
            conn.update_volumes.return_value = []
            conn.create_volume.return_value = "disk1.qcow2"
            setattr(self, name, conn)
        self.url = reverse("storage", args=[self.compute.pk, "default"])
        self.api = f"/api/v1/computes/{self.compute.pk}/storages/default/"

    def test_pool_actions(self):
        for action in ("start", "stop", "set_autostart", "unset_autostart", "delete"):
            self.client.post(self.url, {action: "1"})
        self.assertEqual(rows(), [
            ("Storage pool default: start", True),
            ("Storage pool default: stop", True),
            ("Storage pool default: autostart on", True),
            ("Storage pool default: autostart off", True),
            ("Storage pool default: delete", True),
        ])
        self.assertEqual(set(Logs.objects.values_list("host", flat=True)), {"c1"})

    def test_a_refused_pool_stop(self):
        from vrtManager.util import OperationError

        reason = "Pool default is in use by the running VMs web-1"
        self.pool.stop.side_effect = OperationError(reason)
        response = self.client.post(self.url, {"stop": "1"}, follow=True)
        self.assertIn(reason, [str(m) for m in response.context["messages"]])
        self.assertEqual(rows(), [(f"Storage pool default: stop: {reason}", False)])

    def test_pool_create_and_a_duplicate_name(self):
        url = reverse("storages", args=[self.compute.pk])
        self.client.post(url, {"create": "1", "name": "audit-pool", "stg_type": "dir", "target": "/srv/audit-pool"})
        self.client.post(url, {"create": "1", "name": "bad name!", "stg_type": "dir", "target": "/srv/x"})  # invalid
        self.pools.get_storages_info.return_value = [{"name": "default"}]
        self.pools.create_storage.reset_mock()
        self.client.post(url, {"create": "1", "name": "default", "stg_type": "dir", "target": "/srv/default"})
        self.pools.create_storage.assert_not_called()
        self.assertEqual(rows(), [
            ("Storage pool audit-pool: add", True),
            ("Storage pool default: add: name already in use", False),
        ])

    def test_volume_add_and_delete(self):
        self.client.post(reverse("create_volume", args=[self.compute.pk, "default"]),
                         {"name": "disk1", "format": "qcow2", "size": 1})
        self.client.post(self.url, {"del_volume": "1", "volname": "disk1.qcow2"})
        with patch("storages.views.libvirt_compute_lock", side_effect=claims.Busy("compute:1")):
            self.client.post(self.url, {"del_volume": "1", "volname": "disk1.qcow2"})
        self.assertEqual(rows()[:2], [
            ("Storage pool default: add volume disk1.qcow2", True),
            ("Storage pool default: delete volume disk1.qcow2", True),
        ])
        message, success = rows()[2]
        self.assertFalse(success)
        self.assertTrue(message.startswith("Storage pool default: delete volume disk1.qcow2: "), message)

    def test_the_api_writes_the_same_rows(self):
        self.client.post(self.api + "start/")
        self.client.post(self.api + "stop/")
        self.client.post(self.api + "refresh/")
        self.client.post(self.api + "volumes/", {"name": "disk1", "type": "qcow2", "size": 1, "meta_prealloc": False},
                         content_type="application/json")
        self.client.delete(self.api + "volumes/disk1.qcow2/")
        self.assertEqual(rows(), [
            ("Storage pool default: start", True),
            ("Storage pool default: stop", True),
            ("Storage pool default: add volume disk1.qcow2", True),
            ("Storage pool default: delete volume disk1.qcow2", True),
        ])

    def test_an_inactive_pool_refuses_api_volume_changes(self):
        self.api_pool.is_active.return_value = False
        response = self.client.post(self.api + "volumes/", {"name": "disk2", "type": "qcow2", "size": 1,
                                                             "meta_prealloc": False}, content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.delete(self.api + "volumes/disk2/").status_code, 409)
        self.assertEqual(rows(), [
            ("Storage pool default: add volume disk2: pool is not active", False),
            ("Storage pool default: delete volume disk2: pool is not active", False),
        ])

    def test_the_row_has_actor_ip_and_no_instance(self):
        self.client.post(self.url, {"start": "1"}, REMOTE_ADDR="192.0.2.9")
        row = Logs.objects.get()
        self.assertEqual((row.user, row.host, row.instance, row.ip), ("audit-admin", "c1", "", "192.0.2.9"))

    def test_a_libvirt_reason_is_redacted(self):
        from libvirt import libvirtError

        self.pool.start.side_effect = libvirtError("cannot connect to qemu+tcp://admin:s3cret@192.0.2.5/system")
        self.client.post(self.url, {"start": "1"})  # the middleware answers it
        [(message, success)] = rows()
        self.assertFalse(success)
        self.assertNotIn("s3cret", message)
