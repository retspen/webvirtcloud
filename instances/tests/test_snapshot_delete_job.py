"""External snapshot delete is a job: the request queues it; the worker
deletes through libvirt; recovery follows the reconcile table."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from libvirt import libvirtError

from computes.models import Compute
from instances.jobs import DeleteExternalSnapshot
from instances.models import Instance
from logs.models import Logs
from operations import jobs
from operations.jobs import Context, Outcome
from operations.models import Claim, Operation, acquire
from operations.worker import housekeeping
from vrtManager.instance import wvmInstance


def proxy(listed=("one",), jobs=(), before=None, left=()):
    p = MagicMock()
    p.instance.snapshotListNames.return_value = list(listed)
    p.get_snapshot_jobs.return_value = list(jobs)
    p.snapshot_files_state.return_value = before or {"disks": {}, "own": [], "points": []}
    p.delete_external_snapshot.return_value = list(left)
    p.left_behind_since.return_value = list(left)
    return p


class SnapshotDeleteJobTestCase(TransactionTestCase):
    def setUp(self):
        compute = Compute.objects.create(name="job-compute", hostname="192.0.2.10", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="job-vm",
                                                uuid="11111111-2222-3333-4444-555555555555")
        self.admin = get_user_model().objects.create_superuser("job_admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        Logs.objects.all().delete()  # the login's row
        patcher = patch("instances.jobs.wvmInstance", return_value=proxy())
        self.wvm = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, key="key-00000001", name="one"):
        return self.client.post(
            reverse("instances:delete_external_snapshot", args=[self.instance.pk]),
            {"name": name, "submission_key": key},
            HTTP_REFERER=reverse("instances:instance", args=[self.instance.pk]),
        )

    def test_the_request_queues_one_job_holding_the_vm(self):
        self.post()
        self.post()
        op = Operation.objects.get()
        self.assertEqual((op.kind, op.state, op.params),
                         ("snapshot.delete", Operation.QUEUED, {"instance": self.instance.pk, "name": "one"}))
        self.assertEqual(set(Claim.objects.values_list("resource", "mode")),
                         {(f"compute:{self.instance.compute_id}", "shared"),
                          (f"instance:{self.instance.uuid}", "exclusive")})

    def test_a_retry_after_the_job_ran_returns_it_without_libvirt(self):
        self.post()
        self.wvm.return_value = proxy(listed=())  # the snapshot is gone now
        self.post()
        self.assertEqual(Operation.objects.count(), 1)

    def test_a_second_delete_is_refused_with_its_reason(self):
        self.post(key="key-00000001")
        response = self.post(key="key-00000002")
        self.assertEqual(Operation.objects.count(), 1)
        self.assertTrue(any("Delete snapshot is queued" in str(m) for m in response.wsgi_request._messages))

    def test_a_long_name_is_kept_whole(self):
        # its truncated prefix could name another snapshot
        name = "s" * 100
        self.assertEqual(DeleteExternalSnapshot().normalize({"instance": "1", "name": name})["name"], name)

    def submitted(self):
        return jobs.submit("snapshot.delete", self.admin, {"instance": self.instance.pk, "name": "one"},
                              "key-00000009")

    def test_run_records_the_files_before_the_delete(self):
        op = self.submitted()
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        self.wvm.return_value = proxy(before={"disks": {"vda": ["/p/a"]}, "own": ["/p/a.one"], "points": []},
                                      left=["/p/a.one"])
        ctx = Context(op, SimpleNamespace(identity="wvc-test:1:a"))
        kind = DeleteExternalSnapshot()
        kind.precheck(op, ctx)
        result = kind.run(op, ctx)
        op.refresh_from_db()
        self.wvm.return_value.delete_external_snapshot.assert_called_once_with("one")
        self.assertEqual(op.intent["before"]["own"], ["/p/a.one"])
        self.assertEqual(result, {"left_behind": ["/p/a.one"]})
        jobs.finish(op, Outcome(Operation.SUCCEEDED, result=result))
        row = Logs.objects.get(message="VM job-vm: delete external snapshot one")
        self.assertEqual(row.instance_uuid, self.instance.uuid)

    def logged(self):
        return list(Logs.objects.values_list("user", "host", "instance", "message"))

    def test_every_end_is_logged_with_its_state(self):
        for state in (Operation.FAILED, Operation.UNCERTAIN):
            Logs.objects.all().delete()
            Operation.objects.all().delete()
            op = self.submitted()
            jobs.finish(op, Outcome(state, error="x"))
            self.assertEqual(self.logged(), [("job_admin", "job-compute", "job-vm",
                                              f"VM job-vm: delete external snapshot one ({state})")])
        Logs.objects.all().delete()
        Operation.objects.all().delete()
        jobs.cancel(self.submitted().pk, self.admin)
        self.assertEqual(self.logged(), [("job_admin", "job-compute", "job-vm", "VM job-vm: delete external snapshot one (cancelled)")])

    def test_a_compute_name_with_a_slash_is_logged_whole(self):
        Compute.objects.filter(pk=self.instance.compute_id).update(name="region/job-compute")
        op = self.submitted()
        jobs.finish(op, Outcome(Operation.SUCCEEDED))
        self.assertEqual(self.logged(), [("job_admin", "region/job-compute", "job-vm", "VM job-vm: delete external snapshot one")])

    def test_a_resolved_job_is_logged_on_its_vm(self):
        op = self.submitted()
        jobs.finish(op, Outcome(Operation.UNCERTAIN, error="x"))
        Logs.objects.all().delete()
        jobs.resolve(op.pk, self.admin, Operation.FAILED, "disks checked")
        self.assertEqual(self.logged(), [("job_admin", "job-compute", "job-vm",
                                          f"Job {op.pk} resolved as failed: disks checked")])
        self.assertEqual(Logs.objects.get().instance_uuid, self.instance.uuid)

    def test_retention_keeps_the_log(self):
        op = self.submitted()
        jobs.finish(op, Outcome(Operation.FAILED, error="x"))
        Operation.objects.filter(pk=op.pk).update(finished_at=timezone.now() - timedelta(days=400))
        housekeeping()
        self.assertFalse(Operation.objects.filter(pk=op.pk).exists())
        self.assertEqual([row[3] for row in self.logged()], ["VM job-vm: delete external snapshot one (failed)"])

    def test_precheck_refuses_a_moved_vm_and_an_inactive_user(self):
        op = self.submitted()
        other = Compute.objects.create(name="other", hostname="192.0.2.11", login="root", password="", type=1)
        Instance.objects.filter(pk=self.instance.pk).update(compute=other)
        with self.assertRaisesRegex(Exception, "moved"):
            DeleteExternalSnapshot().precheck(op, Context(op, worker=None))
        Instance.objects.filter(pk=self.instance.pk).update(compute=self.instance.compute)
        get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
        op = Operation.objects.select_related("user").get(pk=op.pk)
        with self.assertRaises(Exception):
            DeleteExternalSnapshot().precheck(op, Context(op, worker=None))

    def reconcile(self, **kw):
        Operation.objects.all().delete()
        self.wvm.return_value = proxy()  # the snapshot exists when the job is submitted
        op = self.submitted()
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, effects_started=True,
                                                  intent={"compute": self.instance.compute_id,
                                                          "before": {"disks": {}, "own": [], "points": []}})
        op.refresh_from_db()
        self.wvm.return_value = proxy(**kw)
        return DeleteExternalSnapshot().reconcile(op)

    def test_reconcile_table(self):
        merging = [{"dev": "vda", "cur": 1, "end": 2}]
        self.assertEqual(self.reconcile(listed=()).state, Operation.SUCCEEDED)
        self.assertEqual(self.reconcile(jobs=merging).state, Operation.RUNNING)
        self.assertEqual(self.reconcile(listed=(), jobs=merging).state, Operation.RUNNING)
        interrupted = self.reconcile()
        self.assertEqual(interrupted.state, Operation.UNCERTAIN)
        self.assertIn("It cannot be told whether the disks changed; check the VM before deleting the snapshot again",
                      interrupted.error)

    def test_reconcile_reports_a_merge_that_stays_at_its_end_as_stalled(self):
        at_end = self.reconcile(jobs=[{"dev": "vda", "cur": 2, "end": 2}, {"dev": "vdb", "cur": 5, "end": 5}])
        self.assertEqual((at_end.state, at_end.stalled), (Operation.RUNNING, True))
        copying = self.reconcile(jobs=[{"dev": "vda", "cur": 2, "end": 2}, {"dev": "vdb", "cur": 1, "end": 5}])
        self.assertEqual((copying.state, copying.stalled), (Operation.RUNNING, False))

    def test_reconcile_reports_the_merge_progress(self):
        merging = self.reconcile(jobs=[{"dev": "vda", "cur": 2, "end": 2}, {"dev": "vdb", "cur": 1, "end": 5}])
        self.assertEqual(merging.progress, (3, 7))

    def test_reconcile_watches_an_offline_merge_of_a_shut_off_vm(self):
        # libvirt reports the merge of a shut-off VM's snapshot as an offline block job
        p = proxy()
        p._XMLDesc.return_value = ("<domain><devices><disk type='file' device='disk'>"
                                   "<source file='/p/a.one'/><target dev='vda'/></disk></devices></domain>")
        p._disk_sources = wvmInstance._disk_sources
        p.instance.isActive.return_value = False
        p.instance.blockJobInfo.side_effect = lambda dev, flags: {"cur": 1, "end": 2, "type": 4}
        p.get_snapshot_jobs = lambda: wvmInstance.get_snapshot_jobs(p)
        Operation.objects.all().delete()
        self.wvm.return_value = proxy()
        op = self.submitted()
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, effects_started=True,
                                                  intent={"compute": self.instance.compute_id,
                                                          "before": {"disks": {}, "own": [], "points": []}})
        op.refresh_from_db()
        self.wvm.return_value = p
        self.assertEqual(DeleteExternalSnapshot().reconcile(op).state, Operation.RUNNING)

    def test_reconcile_of_a_vm_gone_from_its_compute(self):
        err = libvirtError("Domain not found")
        err.err = (42,)  # VIR_ERR_NO_DOMAIN
        Operation.objects.all().delete()
        op = self.submitted()
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, intent={"compute": self.instance.compute_id})
        op.refresh_from_db()
        p = proxy()
        p.instance.snapshotListNames.side_effect = err
        self.wvm.return_value = p
        self.assertEqual(DeleteExternalSnapshot().reconcile(op).state, Operation.UNCERTAIN)
