"""backup.delete: the manifest first, then the other files, then the row;
the Backups page lists every backup."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from lxml import html as lxml_html

from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from operations import jobs
from operations.jobs import Context
from operations.models import Operation, acquire
from vmbackups.jobs import DeleteBackup
from vmbackups.models import Backup, BackupTarget, BackupTargetPool
from vrtManager.util import OperationError

WORKER = "wvc-test:1:a"


class DeleteBackupTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("del_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.31", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="31313131-0000-4000-8000-000000000001")
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u")
        self.backup = Backup.objects.create(target=self.target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                            compute_name="h1", state=Backup.READY)
        prefix = self.backup.prefix
        self.pool = MagicMock()
        self.pool.listVolumes.return_value = [f"{prefix}-vda.qcow2", f"{prefix}-domain.xml", f"{prefix}-manifest.json",
                                              "wvc-00000000-0000-4000-8000-000000000009-vda.qcow2", "other.img"]
        self.removed = []
        for name, value in (
            ("vmbackups.jobs.wvmConnect", MagicMock()),
            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.pool)),
            ("vmbackups.jobs.remove_files", MagicMock(side_effect=lambda pool, names: self.removed.append(list(names)))),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def submit(self):
        op = jobs.submit("backup.delete", self.admin, {"backup": str(self.backup.uuid)}, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op

    def run_job(self, op):
        return DeleteBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def test_the_manifest_goes_first(self):
        self.run_job(self.submit())
        prefix = self.backup.prefix
        self.assertEqual(self.removed, [[f"{prefix}-manifest.json"], [f"{prefix}-vda.qcow2", f"{prefix}-domain.xml"]])
        self.assertFalse(Backup.objects.exists())

    def test_the_pool_is_refreshed_before_the_manifest_is_looked_up(self):
        # another compute made the backup: this one's pool lists its files only after a refresh
        self.pool.refresh.side_effect = lambda flags: self.removed.append("refresh")
        self.run_job(self.submit())
        self.assertEqual(self.removed[0], "refresh")

    def test_an_interrupted_delete_is_finished_by_recovery(self):
        op = self.submit()
        with patch("vmbackups.jobs.remove_files", side_effect=[None, RuntimeError("worker gone")]):
            with self.assertRaises(RuntimeError):
                self.run_job(op)
        self.backup.refresh_from_db()
        self.assertEqual(self.backup.state, Backup.DELETING)
        op.refresh_from_db()
        self.assertEqual(DeleteBackup().reconcile(op).state, Operation.SUCCEEDED)
        self.assertFalse(Backup.objects.exists())

    def test_a_creating_backup_is_not_deleted(self):
        Backup.objects.filter(pk=self.backup.pk).update(state=Backup.CREATING)
        with self.assertRaisesMessage(OperationError, "being made"):
            self.submit()

    def test_a_target_no_compute_reaches_is_refused(self):
        op = self.submit()
        with patch("vmbackups.jobs.target_pool", side_effect=OperationError("Storage pool %(pool)s is gone", pool="b1")):
            with self.assertRaisesMessage(OperationError, "nfs1"):
                self.run_job(op)
        self.assertTrue(Backup.objects.filter(state=Backup.READY).exists())

    def test_the_log_row(self):
        op = self.submit()
        self.run_job(op)
        entry = DeleteBackup().log_entry(op, Operation.SUCCEEDED)
        self.assertEqual(entry[:3], ("h1", "vm1", self.vm.uuid))
        self.assertRegex(entry[3], r"^Backup \d{4}-\d\d-\d\d \d\d:\d\d of vm1 deleted$")

    def test_api_delete(self):
        self.client.force_login(self.admin)
        response = self.client.delete(f"/api/v1/backups/{self.backup.uuid}/", {"submission_key": "key-api-del1"},
                                      content_type="application/json")
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["kind"], "backup.delete")

    def test_the_page_deletes_and_goes_back(self):
        self.client.force_login(self.admin)
        url = reverse("vmbackups:delete", args=[self.backup.uuid])
        response = self.client.post(url, {"submission_key": "key-page-del1"}, HTTP_REFERER="http://testserver/backups/")
        op = Operation.objects.get()
        self.assertEqual(op.kind, "backup.delete")
        # the job's own page: neither the Backups page nor the VM page shows a backup's job
        self.assertRedirects(response, reverse("operations:job", args=[op.pk]), fetch_redirect_response=False)


class IndexTests(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("idx_admin", "a@example.com", "pw")
        compute = Compute.objects.create(name="h1", hostname="192.0.2.32", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="web1", uuid="32323232-0000-4000-8000-000000000001")
        self.t1 = BackupTarget.objects.create(name="nfs1")
        self.t2 = BackupTarget.objects.create(name="nfs2")
        Backup.objects.create(target=self.t1, instance=vm, vm_uuid=vm.uuid, vm_name="web1", compute_name="h1",
                              state=Backup.READY)
        Backup.objects.create(target=self.t2, instance=None, vm_uuid="u2", vm_name="db1", compute_name="h1",
                              state=Backup.FAILED)

    def rows(self, query=""):
        self.client.force_login(self.admin)
        page = lxml_html.fromstring(self.client.get(reverse("vmbackups:index") + query).content)
        return [" ".join(row.text_content().split()) for row in page.xpath("//table[@id='backups']/tbody/tr")]

    def test_the_index_filters_and_marks_removed_vms(self):
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertIn("removed", next(r for r in rows if "db1" in r))
        self.assertNotIn("removed", next(r for r in rows if "web1" in r))
        self.assertEqual(len(self.rows("?vm=WEB")), 1)
        self.assertIn("db1", self.rows(f"?target={self.t2.pk}")[0])
        self.assertIn("db1", self.rows("?state=failed")[0])
        self.assertEqual(self.rows("?state=ready&vm=db"), [])

    def test_only_superusers(self):
        user = get_user_model().objects.create_user("idx_user", password="pw")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("vmbackups:index")).status_code, 403)
