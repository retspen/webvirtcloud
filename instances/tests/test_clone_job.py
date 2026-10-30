"""VM clone runs as a job: the page queues it, the worker clones and records it."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import libvirt
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase
from django.urls import reverse

from accounts.models import UserInstance
from appsettings.settings import get_settings
from computes.models import Compute
from instances.jobs import CloneInstance
from instances.models import Instance
from operations.jobs import Cancelled, Context
from vrtManager.util import OperationError
from operations.models import Claim, Operation, acquire


def proxy():
    p = MagicMock()
    p.get_status.return_value = 5
    p.get_disk_devices.return_value = [{"dev": "vda", "image": "src.qcow2", "size": 1 << 30, "storage": "default"}]
    p.get_net_devices.return_value = [{"mac": "52:54:00:aa:bb:cc"}]
    p.get_vcpu.return_value = 1
    p.get_memory.return_value = 512
    return p


def pool(volumes):
    p = MagicMock()
    p.listVolumes.return_value = volumes
    return p


class CloneJobTestCase(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("clone_admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        self.compute = Compute.objects.create(name="clone-c", hostname="192.0.2.30", login="root", password="", type=1)
        self.source = Instance.objects.create(compute=self.compute, name="src", uuid="12121212-3434-5656-7878-909090909090")
        patcher = patch("instances.models.wvmInstance", return_value=proxy())
        self.proxy = patcher.start().return_value
        self.addCleanup(patcher.stop)

    def test_the_page_queues_the_clone_and_the_worker_makes_and_records_it(self):
        response = self.client.post(reverse("instances:clone", args=[self.source.pk]),
                                    {"name": "copy", "disk-vda": "copy.qcow2", "clone-net-mac-0": "52:54:00:00:00:01",
                                     "submission_key": "key-clone001"})
        self.assertRedirects(response, reverse("instances:instance", args=[self.source.pk]),
                             fetch_redirect_response=False)
        op = Operation.objects.get()
        c = self.compute.pk
        self.assertEqual(set(Claim.objects.values_list("resource", "mode")), {
            (f"compute:{c}", "shared"), (f"reconcile:{c}", "exclusive"),
            (f"instance:{self.source.uuid}", "exclusive"), ("name:copy", "exclusive"),
            (f"volume:{c}:default/copy.qcow2", "exclusive")})
        self.proxy.clone_instance.assert_not_called()

        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        CloneInstance().run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
        self.proxy.clone_instance.assert_called_once_with(op.intent["clone"], op.intent["uuid"])
        clone = Instance.objects.get(uuid=op.intent["uuid"])
        self.assertTrue(UserInstance.objects.filter(instance=clone, user=self.admin).exists())

    def queued(self):
        self.client.post(reverse("instances:clone", args=[self.source.pk]),
                         {"name": "copy", "disk-vda": "copy.qcow2", "clone-net-mac-0": "52:54:00:00:00:01",
                          "submission_key": "key-clone002"})
        return Operation.objects.get()

    def test_the_worker_refuses_a_clone_whose_access_was_revoked(self):
        op = self.queued()
        self.admin.is_superuser = False
        self.admin.save()
        with self.assertRaises(PermissionDenied):
            CloneInstance().precheck(op, None)

    def test_the_worker_refuses_a_clone_whose_source_moved(self):
        op = self.queued()
        other = Compute.objects.create(name="clone-d", hostname="192.0.2.31", login="root", password="", type=1)
        Instance.objects.filter(pk=self.source.pk).update(compute=other)
        with self.assertRaises(OperationError):
            CloneInstance().precheck(op, None)

    @patch("instances.jobs.wvmConnect")
    def test_recovery(self, conn):
        op = Operation(user=self.admin, intent={"compute": self.compute.pk, "uuid": "abababab-0000-1111-2222-333333333333",
                                                "name": "copy", "clone": {"name": "copy", "disk-vda": "copy.qcow2"}})
        self.assertEqual(CloneInstance().reconcile(op).state, Operation.SUCCEEDED)  # the VM is defined
        self.assertTrue(Instance.objects.filter(uuid=op.intent["uuid"]).exists())
        missing = libvirt.libvirtError("no domain")
        missing.err = (libvirt.VIR_ERR_NO_DOMAIN, libvirt.VIR_FROM_QEMU, "no domain")
        conn.return_value.wvm.lookupByUUIDString.side_effect = missing
        conn.return_value.wvm.listAllStoragePools.return_value = [pool(["copy.qcow2", "other.qcow2"])]
        outcome = CloneInstance().reconcile(op)
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertIn("copy.qcow2", outcome.error)

    @patch("instances.jobs.wvmConnect")
    def test_a_clone_that_left_nothing_failed(self, conn):
        op = Operation(user=self.admin, intent={"compute": self.compute.pk, "uuid": "abababab-0000-1111-2222-333333333333",
                                                "name": "copy", "clone": {"name": "copy", "disk-vda": "copy.qcow2"}})
        missing = libvirt.libvirtError("no domain")
        missing.err = (libvirt.VIR_ERR_NO_DOMAIN, libvirt.VIR_FROM_QEMU, "no domain")
        conn.return_value.wvm.lookupByUUIDString.side_effect = missing
        conn.return_value.wvm.listAllStoragePools.return_value = [pool(["other.qcow2"])]
        self.assertEqual(CloneInstance().reconcile(op).state, Operation.FAILED)


def libvirt_error(code):
    err = libvirt.libvirtError("libvirt error")
    err.err = (code, libvirt.VIR_FROM_QEMU, "libvirt error")
    return err


def target(dev):
    return {"dev": dev, "pool": "default", "name": f"copy-{dev}.qcow2",
            "path": f"/pool/copy-{dev}.qcow2", "capacity": 1 << 30, "format": "qcow2"}


class LiveCloneJobTestCase(TransactionTestCase):
    """A running or paused VM is cloned with libvirt's push backup."""

    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("live_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="live-c", hostname="192.0.2.32", login="root", password="", type=1)
        self.source = Instance.objects.create(compute=self.compute, name="src", uuid="23232323-3434-5656-7878-909090909090")
        self.proxy = proxy()
        for target_name in ("instances.models.wvmInstance", "instances.jobs.wvmInstance"):
            patcher = patch(target_name, return_value=self.proxy)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("instances.jobs.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events = []
        p = self.proxy
        p.get_status.return_value = 1
        p.is_agent_ready.return_value = True
        p.live_clone_targets.return_value = [target("vda"), target("vdb")]
        p.create_clone_target.side_effect = self.created
        for name in ("fs_freeze", "fs_thaw", "begin_clone_backup", "define_clone", "abort_backup",
                     "discard_backup_result"):
            self.track(name)
        p.backup_progress.side_effect = [(1, 2), None]
        p.backup_result.return_value = (True, "")
        p.backup_targets.return_value = None

    def track(self, name, error=None):
        def call(*args):
            self.events.append(name)
            if error is not None:
                raise error
        getattr(self.proxy, name).side_effect = call

    def created(self, t, uid, gid):
        self.events.append(("create", t["dev"]))
        return f"/real/{t['name']}"  # libvirt's path, not the planned one

    def op(self, **intent):
        return Operation.objects.create(
            kind="instance.clone", user=self.admin, username=self.admin.username, submission_key=f"key-{uuid4().hex[:12]}",
            resource=f"instance:{self.source.uuid}", resource_label="live-c/src", params={"instance": self.source.pk},
            intent={"compute": self.compute.pk, "uuid": "cdcdcdcd-0000-1111-2222-333333333333", "name": "copy",
                    "clone": {"name": "copy", "disk-vda": "copy-vda.qcow2", "disk-vdb": "copy-vdb.qcow2",
                              "disk_owner_uid": 107, "disk_owner_gid": 107}, **intent})

    def run_job(self, op):
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        test = self

        class Recording(Context):
            def record_intent(self, **values):
                test.events.append(("intent", *sorted(values)))
                super().record_intent(**values)

        return CloneInstance().run(op, Recording(op, SimpleNamespace(identity="wvc-test:1:a")))

    def deleted(self):
        return [c.args[0] for c in self.proxy.get_volume_by_path.call_args_list]

    # path choice and claims

    def test_a_shut_off_vm_is_copied_as_before(self):
        self.proxy.get_status.return_value = 5
        op = self.op()
        CloneInstance().precheck(op, None)
        self.run_job(op)
        self.proxy.clone_instance.assert_called_once_with(op.intent["clone"], op.intent["uuid"])
        self.proxy.live_clone_targets.assert_not_called()
        self.assertFalse(Operation.objects.get(pk=op.pk).intent["live"])

    def test_a_name_taken_since_the_job_was_queued_stops_it(self):
        op = self.op()
        other = Compute.objects.create(name="live-d", hostname="192.0.2.33", login="root", password="", type=1)
        Instance.objects.create(compute=other, name="copy", uuid="cdcdcdcd-9999-1111-2222-333333333333")
        with self.assertRaisesMessage(OperationError, "already exists"):
            CloneInstance().precheck(op, None)

    def test_a_running_or_paused_vm_takes_the_live_path(self):
        for status in (1, 3):
            with self.subTest(status=status):
                Instance.objects.filter(name="copy").delete()  # the clone of the run before
                self.proxy.reset_mock()
                self.proxy.get_status.return_value = status
                self.proxy.backup_progress.side_effect = [None]
                op = self.op()
                CloneInstance().precheck(op, None)
                self.assertEqual(self.proxy.live_clone_targets.call_count, 1)
                self.run_job(op)
                self.proxy.clone_instance.assert_not_called()
                self.proxy.begin_clone_backup.assert_called_once()
                intent = Operation.objects.get(pk=op.pk).intent
                self.assertTrue(intent["live"])
                op.delete()

    def test_another_state_is_refused(self):
        self.proxy.get_status.return_value = 4  # shutting down
        with self.assertRaisesMessage(OperationError, "The VM must be running, paused or shut off to be cloned"):
            CloneInstance().precheck(self.op(), None)
        with self.assertRaisesMessage(OperationError, "The VM must be running, paused or shut off to be cloned"):
            CloneInstance().plan(self.admin, {"instance": self.source.pk, "fields": {
                "name": "copy", "disk-vda": "copy.qcow2", "clone-net-mac-0": "52:54:00:00:00:01"}})

    def test_plan_holds_the_source_and_each_target_volume(self):
        self.proxy.get_disk_devices.return_value = [
            {"dev": "vda", "image": "src.qcow2", "size": 1 << 30, "storage": "default"},
            {"dev": "vdb", "image": "data.raw", "size": 1 << 30, "storage": "fast"}]
        plan = CloneInstance().plan(self.admin, {"instance": self.source.pk, "fields": {
            "name": "copy", "disk-vda": "copy.qcow2", "disk-vdb": "copy.raw", "clone-net-mac-0": "52:54:00:00:00:01"}})
        c = self.compute.pk
        self.assertEqual(plan.claims[f"instance:{self.source.uuid}"], Claim.EXCLUSIVE)
        self.assertEqual(plan.claims[f"volume:{c}:default/copy.qcow2"], Claim.EXCLUSIVE)
        self.assertEqual(plan.claims[f"volume:{c}:fast/copy.raw"], Claim.EXCLUSIVE)
        self.proxy.live_clone_targets.assert_called_once()  # a running VM is refused early

    # run

    def test_the_live_run_records_each_step_before_it(self):
        op = self.op()
        self.assertEqual(self.run_job(op), {})
        self.assertEqual(self.events, [
            ("intent", "live", "targets"),
            ("intent", "planned"), ("create", "vda"), ("intent", "created"),
            ("intent", "planned"), ("create", "vdb"), ("intent", "created"),
            "discard_backup_result", ("intent", "copy_started"),
            ("intent", "frozen"), "fs_freeze", "begin_clone_backup", "fs_thaw", ("intent", "frozen"),
            ("intent", "copy_result"), "define_clone"])
        intent = Operation.objects.get(pk=op.pk).intent
        self.assertEqual(intent["planned"], [{"dev": "vda", "path": "/pool/copy-vda.qcow2"},
                                             {"dev": "vdb", "path": "/pool/copy-vdb.qcow2"}])
        self.assertEqual(intent["created"], [{"dev": "vda", "path": "/real/copy-vda.qcow2"},
                                             {"dev": "vdb", "path": "/real/copy-vdb.qcow2"}])
        self.assertEqual((intent["frozen"], intent["copy_result"]), (False, [True, ""]))
        backup = self.proxy.begin_clone_backup.call_args.args[0]
        self.assertEqual([t["path"] for t in backup], ["/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"])
        self.proxy.define_clone.assert_called_once_with(
            op.intent["clone"], op.intent["uuid"], {"vda": "/real/copy-vda.qcow2", "vdb": "/real/copy-vdb.qcow2"})
        clone = Instance.objects.get(uuid=op.intent["uuid"])
        self.assertTrue(UserInstance.objects.filter(instance=clone, user=self.admin).exists())
        self.assertEqual(self.deleted(), [])

    def test_a_paused_vm_or_one_without_a_ready_agent_is_not_frozen(self):
        for status, agent in ((3, True), (1, False)):
            with self.subTest(status=status, agent=agent):
                self.events.clear()
                self.proxy.get_status.return_value = status
                self.proxy.is_agent_ready.return_value = agent
                self.proxy.backup_progress.side_effect = [None]
                op = self.op()
                self.run_job(op)
                self.assertNotIn("fs_freeze", self.events)
                self.assertNotIn("fs_thaw", self.events)
                self.assertIn("begin_clone_backup", self.events)
                op.delete()

    def recover(self, op, defined=False):
        op.refresh_from_db()
        with patch("instances.jobs.wvmConnect") as conn:
            if not defined:
                conn.return_value.wvm.lookupByUUIDString.side_effect = libvirt_error(libvirt.VIR_ERR_NO_DOMAIN)
            return CloneInstance().reconcile(op)

    def test_a_backup_that_did_not_start_failed(self):
        self.track("begin_clone_backup", libvirt_error(libvirt.VIR_ERR_OPERATION_INVALID))
        op = self.op()
        with self.assertRaises(libvirt.libvirtError):
            self.run_job(op)
        self.assertEqual(self.events[-4:], ["begin_clone_backup", "fs_thaw", ("intent", "frozen"),
                                            ("intent", "copy_result")])
        intent = Operation.objects.get(pk=op.pk).intent
        self.assertFalse(intent["frozen"])
        self.assertEqual(intent["copy_result"], [False, "libvirt error"])
        # an earlier job's completed result was dropped before copy_started
        self.assertLess(self.events.index("discard_backup_result"), self.events.index(("intent", "copy_started")))
        self.assertEqual(self.deleted(), [])  # recovery deletes them
        outcome = self.recover(op)
        self.assertEqual((outcome.state, outcome.error), (Operation.FAILED, "libvirt error"))
        self.assertNotIn("define_clone", self.events)
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"])

    def test_the_guest_is_thawed_when_the_freeze_fails(self):
        self.track("fs_freeze", libvirt_error(libvirt.VIR_ERR_AGENT_UNRESPONSIVE))
        op = self.op()
        with self.assertRaises(libvirt.libvirtError):
            self.run_job(op)
        self.assertEqual(self.events[-5:], [("intent", "frozen"), "fs_freeze", "fs_thaw", ("intent", "frozen"),
                                            ("intent", "copy_result")])
        self.proxy.begin_clone_backup.assert_not_called()
        self.assertEqual(self.recover(op).state, Operation.FAILED)
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"])

    def test_a_failed_thaw_leaves_the_thaw_to_recovery(self):
        self.track("fs_freeze", libvirt_error(libvirt.VIR_ERR_AGENT_UNRESPONSIVE))
        self.track("fs_thaw", libvirt_error(libvirt.VIR_ERR_AGENT_UNRESPONSIVE))
        op = self.op()
        with self.assertRaises(libvirt.libvirtError):
            self.run_job(op)
        self.assertTrue(Operation.objects.get(pk=op.pk).intent["frozen"])
        self.events.clear()
        outcome = self.recover(op)
        self.assertEqual(self.events[0], "fs_thaw")
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertIn("virsh domfsthaw src", outcome.error)

    def test_a_lost_connection_while_the_backup_starts_is_recoverys(self):
        self.track("begin_clone_backup", libvirt_error(libvirt.VIR_ERR_INTERNAL_ERROR))
        self.proxy.backup_targets.side_effect = libvirt_error(libvirt.VIR_ERR_INTERNAL_ERROR)
        op = self.op()
        with self.assertRaises(libvirt.libvirtError):
            self.run_job(op)
        self.assertNotIn("copy_result", Operation.objects.get(pk=op.pk).intent)
        self.proxy.backup_targets.side_effect = None
        self.proxy.backup_result.return_value = None  # dropped before copy_started
        self.assertEqual(self.recover(op).state, Operation.UNCERTAIN)
        self.assertEqual(self.deleted(), [])

    def test_a_cancel_while_the_backup_starts_aborts_it(self):
        op = self.op()

        def begin(*args):  # the cancel hook found no backup yet
            self.events.append("begin_clone_backup")
            Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
            self.proxy.backup_targets.return_value = {"/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"}
        self.proxy.begin_clone_backup.side_effect = begin
        self.track("abort_backup", libvirt_error(libvirt.VIR_ERR_OPERATION_INVALID))  # the hook was first
        self.proxy.backup_result.return_value = (False, "Operation canceled")
        with self.assertRaises(Cancelled):
            self.run_job(op)
        self.assertLess(self.events.index("begin_clone_backup"), self.events.index("abort_backup"))
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"])

    def test_a_thaw_error_is_a_warning_of_the_result(self):
        self.track("fs_thaw", libvirt_error(libvirt.VIR_ERR_AGENT_UNRESPONSIVE))
        result = self.run_job(self.op())
        self.assertIn("could not be thawed", result["warning"])
        self.assertIn("thaw them with: virsh domfsthaw src", result["warning"])
        self.proxy.define_clone.assert_called_once()

    def test_a_failed_copy_deletes_only_what_the_job_created(self):
        self.proxy.backup_result.return_value = (False, "No space left on device")
        op = self.op()
        with self.assertRaisesMessage(OperationError, "No space left on device"):
            self.run_job(op)
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"])
        self.proxy.define_clone.assert_not_called()

    def test_a_cancelled_copy_ends_cancelled(self):
        self.proxy.backup_result.return_value = (False, "Operation canceled")
        op = self.op()

        def progress():  # the cancel comes while the copy runs
            Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
            return None
        self.proxy.backup_progress.side_effect = progress
        with self.assertRaises(Cancelled):
            self.run_job(op)
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"])

    def test_a_cancel_before_the_copy_starts_ends_cancelled_without_it(self):
        op = self.op()
        Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        with self.assertRaises(Cancelled):
            self.run_job(op)
        self.proxy.begin_clone_backup.assert_not_called()
        self.proxy.fs_freeze.assert_not_called()
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2", "/real/copy-vdb.qcow2"])

    def test_a_copy_that_succeeded_wins_over_a_late_cancel(self):
        op = self.op()

        def progress():
            Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
            return None
        self.proxy.backup_progress.side_effect = progress
        self.run_job(op)
        self.proxy.define_clone.assert_called_once()
        self.assertEqual(self.deleted(), [])

    def test_no_result_goes_to_recovery(self):
        self.proxy.backup_result.return_value = None
        op = self.op()
        with self.assertRaises(OperationError):
            self.run_job(op)
        self.assertIsNone(Operation.objects.get(pk=op.pk).intent["copy_result"])
        self.assertEqual(self.deleted(), [])

    # cancel and progress

    CREATED = [{"dev": "vda", "path": "/real/copy-vda.qcow2"}]

    def test_cancel_aborts_only_this_jobs_backup(self):
        op = self.op(live=True, created=self.CREATED)
        for targets, aborted in ((None, False), ({"/other/x.qcow2"}, False), ({"/real/copy-vda.qcow2"}, True)):
            with self.subTest(targets=targets):
                self.events.clear()
                self.proxy.backup_targets.return_value = targets
                CloneInstance().cancel(op)
                self.assertEqual("abort_backup" in self.events, aborted)

    def test_a_shut_off_clone_ignores_a_cancel(self):
        self.proxy.get_status.return_value = 5
        op = self.op(live=False)
        CloneInstance().cancel(op)
        self.proxy.backup_targets.assert_not_called()
        Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        op.refresh_from_db()
        self.run_job(op)
        self.proxy.clone_instance.assert_called_once()

    def test_progress_of_a_live_clone_is_the_backups_bytes(self):
        self.proxy.backup_progress.side_effect = None
        self.proxy.backup_progress.return_value = (3, 8)
        self.assertEqual(CloneInstance().progress(self.op(live=True)), (3, 8))
        self.assertIsNone(CloneInstance().progress(self.op(live=False)))
        self.assertTrue(CloneInstance.progress_bytes)
        self.assertTrue(CloneInstance.cancellable)
        self.assertIsNone(CloneInstance.time_limit)  # the worker never cancels a long copy

    # recovery

    def recovered(self, cancel=False, defined=False, **intent):
        base = {"live": True, "targets": [target("vda")],
                "planned": [{"dev": "vda", "path": "/pool/copy-vda.qcow2"}], "created": self.CREATED,
                "copy_started": True}
        op = self.op(**{**base, **intent})
        op.cancel_requested = cancel
        op.save()
        with patch("instances.jobs.wvmConnect") as conn:
            if not defined:
                conn.return_value.wvm.lookupByUUIDString.side_effect = libvirt_error(libvirt.VIR_ERR_NO_DOMAIN)
            return CloneInstance().reconcile(op), op

    def test_recovery_before_the_copy_deletes_what_was_created(self):
        outcome, _op = self.recovered(copy_started=None)
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2"])
        self.proxy.reset_mock()
        outcome, _op = self.recovered(copy_started=None, cancel=True)
        self.assertEqual(outcome.state, Operation.CANCELLED)

    def test_recovery_of_a_volume_being_created_is_uncertain(self):
        outcome, _op = self.recovered(copy_started=None, created=[],
                                      planned=[{"dev": "vda", "path": "/pool/copy-vda.qcow2"}])
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertIn("/pool/copy-vda.qcow2", outcome.error)
        self.proxy.wvm.storagePoolLookupByName.assert_called_with("default")
        self.proxy.wvm.storagePoolLookupByName.return_value.storageVolLookupByName.assert_called_with("copy-vda.qcow2")
        self.proxy.get_volume_by_path.return_value.delete.assert_not_called()
        self.proxy.wvm.storagePoolLookupByName.return_value.storageVolLookupByName.side_effect = libvirt_error(
            libvirt.VIR_ERR_NO_STORAGE_VOL)
        outcome, _op = self.recovered(copy_started=None, created=[])
        self.assertEqual(outcome.state, Operation.FAILED)  # it was never made

    def test_recovery_watches_this_jobs_backup(self):
        self.proxy.backup_targets.return_value = {"/real/copy-vda.qcow2"}
        self.proxy.backup_progress.side_effect = None
        self.proxy.backup_progress.return_value = (1, 4)
        outcome, _op = self.recovered()
        self.assertEqual((outcome.state, outcome.progress), (Operation.RUNNING, (1, 4)))
        self.proxy.backup_targets.return_value = {"/other/x.qcow2"}
        outcome, _op = self.recovered()
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertEqual(self.deleted(), [])

    def test_recovery_defines_the_clone_of_a_successful_copy(self):
        for intent in ({"copy_result": [True, ""]}, {}):
            with self.subTest(intent=intent):
                self.events.clear()
                outcome, op = self.recovered(**intent)
                self.assertEqual(outcome.state, Operation.SUCCEEDED)
                self.proxy.define_clone.assert_called_with(op.intent["clone"], op.intent["uuid"],
                                                           {"vda": "/real/copy-vda.qcow2"})
                self.assertTrue(Instance.objects.filter(uuid=op.intent["uuid"]).exists())
                Instance.objects.filter(uuid=op.intent["uuid"]).delete()
                op.delete()

    def test_recovery_of_a_defined_clone_succeeds(self):
        self.proxy.backup_result.return_value = None  # libvirtd restarted after the clone was defined
        self.proxy.backup_targets.return_value = {"/other/x.qcow2"}  # checked after it
        outcome, op = self.recovered(defined=True)
        self.assertEqual(outcome.state, Operation.SUCCEEDED)
        self.assertNotIn("define_clone", self.events)
        self.assertTrue(Instance.objects.filter(uuid=op.intent["uuid"]).exists())

    def test_recovery_of_a_failed_copy_deletes_what_was_created(self):
        outcome, _op = self.recovered(copy_result=[False, "No space left on device"])
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertIn("No space left on device", outcome.error)
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2"])
        outcome, _op = self.recovered(copy_result=[False, "Operation canceled"], cancel=True)
        self.assertEqual(outcome.state, Operation.CANCELLED)

    def test_a_recorded_failure_wins_over_another_tools_backup(self):
        self.proxy.backup_targets.return_value = {"/other/x.qcow2"}
        outcome, _op = self.recovered(copy_result=[False, "another backup runs"])
        self.assertEqual((outcome.state, outcome.error), (Operation.FAILED, "another backup runs"))
        self.assertEqual(self.deleted(), ["/real/copy-vda.qcow2"])
        outcome, _op = self.recovered(copy_result=[False, "another backup runs"], cancel=True)
        self.assertEqual(outcome.state, Operation.CANCELLED)

    def test_recovery_without_a_result_is_uncertain(self):
        self.proxy.backup_result.return_value = None
        outcome, _op = self.recovered()
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertIn("/real/copy-vda.qcow2", outcome.error)
        self.assertEqual(self.deleted(), [])

    def test_recovery_thaws_a_guest_left_frozen_first(self):
        self.proxy.backup_targets.side_effect = lambda: self.events.append("backup_targets")
        self.recovered(frozen=True)
        self.assertEqual(self.events[:2], ["fs_thaw", "backup_targets"])
        self.events.clear()
        self.proxy.get_status.return_value = 5
        self.recovered(frozen=True)
        self.assertNotIn("fs_thaw", self.events)
