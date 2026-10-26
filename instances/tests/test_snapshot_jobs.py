"""Snapshot create and revert run as jobs: the page queues them, the worker calls libvirt."""

from types import SimpleNamespace
from unittest.mock import patch

from vrtManager.util import OperationError
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse

from appsettings.settings import get_settings
from computes.models import Compute
from instances.jobs import CreateSnapshot, RevertSnapshot
from instances.models import Instance
from operations.jobs import Context, get_kind
from operations.models import Claim, Operation, acquire


class SnapshotJobsTestCase(TransactionTestCase):
    def setUp(self):
        get_settings()
        compute = Compute.objects.create(name="snap-c", hostname="192.0.2.40", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="snap-vm",
                                                uuid="21212121-3434-5656-7878-909090909090")
        self.client.force_login(get_user_model().objects.create_superuser("snap_admin", "a@example.com", "pw"))
        patcher = patch("instances.jobs.wvmInstance")
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.proxy.instance.snapshotListNames.return_value = []
        self.proxy.instance.isActive.return_value = False
        self.proxy.instance.hasCurrentSnapshot.return_value = 0

    def queue_and_run(self, view, data):
        """Post the form; nothing runs in the request; then run the job as the worker does."""
        self.client.post(reverse(f"instances:{view}", args=[self.instance.pk]),
                         {**data, "submission_key": "key-snap0001"})
        op = Operation.objects.get()
        self.assertIn((f"instance:{self.instance.uuid}", "exclusive"),
                      set(Claim.objects.values_list("resource", "mode")))
        self.assertFalse(self.proxy.create_snapshot.called or self.proxy.create_external_snapshot.called
                         or self.proxy.snapshot_revert.called or self.proxy.revert_external_snapshot.called)
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        ctx = Context(op, SimpleNamespace(identity="wvc-test:1:a"))
        kind = get_kind(op.kind)
        kind.precheck(op, ctx)
        return op, kind.run(op, ctx)

    def test_an_external_snapshot_is_taken_by_the_worker(self):
        op, _ = self.queue_and_run("create_external_snapshot", {"name": "a", "description": "d", "memory": "on"})
        self.assertEqual(op.kind, "snapshot.create")
        self.assertEqual(self.proxy.create_external_snapshot.call_args.args, ("a", "d", True, False))

    def test_an_internal_snapshot_is_taken_by_the_worker(self):
        self.queue_and_run("snapshot", {"name": "b"})
        self.proxy.create_snapshot.assert_called_once_with("b", "")

    def test_a_taken_name_is_refused_on_the_page(self):
        self.proxy.instance.snapshotListNames.return_value = ["a"]
        self.client.post(reverse("instances:snapshot", args=[self.instance.pk]),
                         {"name": "a", "submission_key": "key-snap0001"})
        self.assertFalse(Operation.objects.exists())

    def test_a_name_that_is_empty_or_not_a_snapshot_name_is_refused_on_the_page(self):
        for name in ("", ".hidden", "a b"):
            response = self.client.post(reverse("instances:snapshot", args=[self.instance.pk]),
                                        {"name": name, "submission_key": "key-snap0001"}, follow=True)
            self.assertContains(response, "Snapshot names are 1-64 letters")
        self.assertFalse(Operation.objects.exists())

    def test_create_recovery(self):
        op = Operation(params={"instance": self.instance.pk, "name": "a", "external": True},
                       intent={"compute": self.instance.compute_id})
        self.assertEqual(CreateSnapshot().reconcile(op).state, Operation.FAILED)
        self.proxy.instance.snapshotListNames.return_value = ["a"]
        self.assertEqual(CreateSnapshot().reconcile(op).state, Operation.SUCCEEDED)
        self.proxy.instance.isActive.return_value = True
        self.proxy.instance.jobInfo.return_value = [2] + [0] * 11  # VIR_DOMAIN_JOB_UNBOUNDED
        self.assertEqual(CreateSnapshot().reconcile(op).state, Operation.RUNNING)

    def test_an_external_revert_is_made_by_the_worker(self):
        self.proxy.revert_external_snapshot.return_value = ["/pool/a.one"]
        op, result = self.queue_and_run("revert_external_snapshot", {"name": "a"})
        self.assertEqual((op.kind, result), ("snapshot.revert", {"left_behind": ["/pool/a.one"]}))
        self.proxy.revert_external_snapshot.assert_called_once_with("a")

    def test_a_revert_libvirt_cannot_do_is_refused_before_effects(self):
        self.proxy.check_external_revert.side_effect = OperationError("taken by an older version")
        with self.assertRaises(OperationError):
            self.queue_and_run("revert_external_snapshot", {"name": "a"})
        self.assertFalse(Operation.objects.get().effects_started)

    def test_an_internal_revert_is_made_by_the_worker(self):
        self.queue_and_run("revert_snapshot", {"name": "b"})
        self.proxy.snapshot_revert.assert_called_once_with("b")

    def test_revert_recovery(self):
        op = Operation(params={"instance": self.instance.pk, "name": "a", "external": False},
                       intent={"compute": self.instance.compute_id, "was_current": "z"})
        self.proxy.instance.hasCurrentSnapshot.return_value = 1
        self.proxy.instance.snapshotCurrent.return_value.getName.return_value = "a"
        self.assertEqual(RevertSnapshot().reconcile(op).state, Operation.SUCCEEDED)
        op.intent["was_current"] = "a"  # it was current before: nothing tells
        self.assertEqual(RevertSnapshot().reconcile(op).state, Operation.UNCERTAIN)
