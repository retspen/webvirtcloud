"""backup.restore_disk: one disk of a ready backup copied as a new volume
into a pool of a compute that has the target's pool."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import libvirt
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from appsettings.settings import get_settings
from computes.models import Compute
from operations import jobs
from operations.jobs import Context
from operations.models import Claim, Operation, acquire
from vmbackups.jobs import RestoreDisk
from vmbackups.models import Backup, BackupFile, BackupTarget, BackupTargetPool
from vrtManager.util import OperationError

GIB = 1024**3
WORKER = "wvc-test:1:a"


def error(code):
    err = libvirt.libvirtError("x")
    err.err = (code,)
    return err


class RestoreDiskTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("rd_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.61", login="u", password="p", type=1)
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u")
        self.backup = Backup.objects.create(target=self.target, vm_uuid="61616161-0000-4000-8000-000000000001",
                                            vm_name="vm1", compute_name="h1", state=Backup.READY)
        Backup.objects.filter(pk=self.backup.pk).update(created_at=timezone.make_aware(timezone.datetime(2026, 11, 17, 11, 40)))
        BackupFile.objects.create(backup=self.backup, role=BackupFile.DISK, dev="vdb", volume=f"{self.backup.prefix}-vdb.raw",
                                  format="raw", capacity=GIB)
        self.conn = MagicMock()
        self.dest = MagicMock()
        self.dest.info.return_value = [2, 100 * GIB, 0, 100 * GIB]
        self.dest.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        self.conn.file_pools.return_value = {"default": (self.dest, "/dest")}
        self.tpool = MagicMock()
        self.tpool.storageVolLookupByName.return_value.info.return_value = [0, GIB, GIB]
        self.storage = MagicMock()
        self.storage.clone_volume.side_effect = lambda vol, name, **kw: f"/dest/{name}"
        for name, value in (
            ("vmbackups.jobs.wvmConnect", MagicMock(return_value=self.conn)),
            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.tpool)),
            ("vmbackups.jobs.wvmStorage", MagicMock(return_value=self.storage)),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def submit(self, **fields):
        raw = {"backup": str(self.backup.uuid), "dev": "vdb", "compute": self.compute.pk, "pool": "default",
               "name": "vm1-vdb-restored.raw", **fields}
        op = jobs.submit("backup.restore_disk", self.admin, raw, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op

    def run_job(self, op):
        return RestoreDisk().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def interrupted(self, op):
        with self.assertRaises(Exception):
            self.run_job(op)
        op.refresh_from_db()
        return op

    def test_the_disk_is_copied_as_a_new_volume(self):
        op = self.submit()
        self.assertTrue(Claim.objects.filter(operation=op, resource=f"volume:{self.compute.pk}:default/vm1-vdb-restored.raw",
                                             mode=Claim.EXCLUSIVE).exists())
        self.assertEqual(self.run_job(op), {"open": reverse("storage", args=[self.compute.pk, "default"])})
        vol, name = self.storage.clone_volume.call_args.args
        self.assertEqual((name, self.storage.clone_volume.call_args.kwargs["vol_fmt"]), ("vm1-vdb-restored.raw", "raw"))

    def test_a_disk_the_backup_does_not_have_is_refused(self):
        with self.assertRaisesMessage(OperationError, "vdc"):
            self.submit(dev="vdc")

    def test_a_name_with_a_slash_is_refused(self):
        with self.assertRaisesMessage(OperationError, "../x.raw"):
            self.submit(name="../x.raw")

    def test_a_taken_name_is_refused_before_copying(self):
        self.dest.storageVolLookupByName.side_effect = None
        with self.assertRaisesMessage(OperationError, "vm1-vdb-restored.raw"):
            self.run_job(self.submit())
        self.storage.clone_volume.assert_not_called()

    def test_a_failed_copy_fails(self):
        self.storage.clone_volume.side_effect = libvirt.libvirtError("No space left on device")
        op = self.interrupted(self.submit())
        self.assertEqual(RestoreDisk().reconcile(op).state, Operation.FAILED)

    def test_a_volume_left_by_a_failed_copy_is_removed(self):
        # createXMLFrom made it, then reading its path failed
        self.storage.clone_volume.side_effect = libvirt.libvirtError("cannot read path")
        removed = []
        with patch("vmbackups.jobs.remove_files", side_effect=lambda pool, names: removed.extend(names)):
            op = self.interrupted(self.submit())
        self.assertEqual(removed, ["vm1-vdb-restored.raw"])
        self.assertEqual(RestoreDisk().reconcile(op).state, Operation.FAILED)

    def test_a_copy_in_flight_is_uncertain(self):
        self.storage.clone_volume.side_effect = RuntimeError("worker gone")
        op = self.interrupted(self.submit())
        outcome = RestoreDisk().reconcile(op)
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertIn("vm1-vdb-restored.raw", outcome.error[0]["values"]["volume"])

    def test_a_copy_done_before_the_worker_stopped_succeeds(self):
        op = self.submit()
        self.run_job(op)
        op.refresh_from_db()
        self.assertEqual(RestoreDisk().reconcile(op).state, Operation.SUCCEEDED)

    def test_the_log_row(self):
        op = self.submit()
        entry = RestoreDisk().log_entry(op, Operation.SUCCEEDED)
        self.assertEqual(entry[0], "h1")
        self.assertEqual(entry[3], "VM vm1: disk vdb of the backup taken 2026-11-17 11:40 restored as vm1-vdb-restored.raw "
                                   "in default")

    def test_the_page_submits_the_job(self):
        from lxml import html as lxml_html

        self.client.force_login(self.admin)
        url = reverse("vmbackups:restore_disk", args=[self.backup.uuid])
        page = lxml_html.fromstring(self.client.get(url).content)
        self.assertEqual(page.xpath("//select[@name='dev']/option/@value"), ["vdb"])
        self.assertEqual(page.xpath("string(//input[@name='name']/@value)"), "vm1-vdb-restored.raw")
        response = self.client.post(url, {"dev": "vdb", "compute": self.compute.pk, "pool": "default",
                                          "name": "vm1-vdb-restored.raw", "submission_key": "key-page-disk1"})
        op = Operation.objects.get(kind="backup.restore_disk")
        self.assertRedirects(response, reverse("operations:job", args=[op.pk]), fetch_redirect_response=False)

    def test_api_restore_disk(self):
        self.client.force_login(self.admin)
        response = self.client.post(f"/api/v1/backups/{self.backup.uuid}/restore-disk/",
                                    {"dev": "vdb", "compute": self.compute.pk, "name": "x.raw", "submission_key": "key-api-disk1"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["kind"], "backup.restore_disk")
