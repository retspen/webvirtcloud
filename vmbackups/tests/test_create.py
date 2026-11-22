"""backup.create: a VM backed up into a target, offline or live, published
last with its manifest, recovered from where the worker stopped."""

import itertools
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import libvirt
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from lxml import html as lxml_html

from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from instances.tests.test_page_controls import PageControls
from operations import jobs
from operations.jobs import Cancelled, Context
from operations.models import Operation, acquire
from vmbackups.jobs import CreateBackup, _owner
from vmbackups.models import Backup, BackupFile, BackupTarget, BackupTargetPool
from vrtManager.util import OperationError

GIB = 1024**3
MIB = 1024**2
WORKER = "wvc-test:1:a"
NVRAM = "/var/lib/libvirt/qemu/nvram/vm1_VARS.fd"


def libvirt_error(text="x"):
    return libvirt.libvirtError(text)


def plan(nvram=None, tpm=False):
    return {
        "definition": "<domain><name>vm1</name></domain>",
        "disks": [{"dev": "vda", "path": "/pool/a.qcow2", "pool": "default", "format": "qcow2", "capacity": GIB}],
        "nvram": nvram,
        "tpm": tpm,
        "left_out": [{"dev": "sda", "why": "CD-ROM: not copied"}],
    }


def proxy(status=libvirt.VIR_DOMAIN_SHUTOFF, nvram=None):
    p = MagicMock()
    p.get_status.return_value = status
    p.backup_plan.return_value = plan(nvram)
    p.wvm.getLibVersion.return_value = 11_010_000
    p.wvm.getVersion.return_value = 10_001_000
    p.is_agent_ready.return_value = True
    p.make_live_targets.side_effect = lambda disks, pool, names, uid, gid, backing=None: [
        {"dev": d["dev"], "path": f"/b1/{names[d['dev']]}", "format": d["format"]} for d in disks]
    p.backup_targets.return_value = None
    p.backup_progress.return_value = None
    p.backup_result.return_value = (True, "")
    p.read_nvram.return_value = b"vars"
    p.read_tpm.return_value = {"tpm2-00.permall": b"state"}
    return p


def target_pool():
    pool = MagicMock()
    pool.name.return_value = "b1"
    pool.info.return_value = [2, 100 * GIB, 0, 100 * GIB]
    pool.storageVolLookupByName.return_value.info.return_value = [0, GIB, GIB // 2]
    return pool


class CreateBackupTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("bk_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.21", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="21212121-0000-4000-8000-000000000001")
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="pool-uuid")
        self.proxy = proxy()
        self.pool = target_pool()
        self.written = []
        self.modes = {}
        self.removed = []
        for name, value in (
            ("vmbackups.jobs.wvmBackup", MagicMock(return_value=self.proxy)),
            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.pool)),
            ("vmbackups.jobs.put_file", MagicMock(side_effect=self.put_file)),
            ("vmbackups.jobs.remove_files", MagicMock(side_effect=lambda pool, names: self.removed.extend(names))),
            ("vmbackups.jobs.NVRAM_WAIT", 0),
            ("vmbackups.jobs.PROGRESS_EVERY", 0),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    fail_on = None

    def put_file(self, conn, pool, name, data, owner, mode="0644"):
        if self.fail_on and name.endswith(self.fail_on):
            raise libvirt_error("No space left on device")
        self.written.append(name)
        self.modes[name] = mode
        return "sha"

    def submit(self, frozen=False):
        op = jobs.submit("backup.create", self.admin, {"instance": self.vm.pk, "target": self.target.pk, "frozen": frozen},
                         f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op

    def run_job(self, op):
        return CreateBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def interrupted(self, op, error=None):
        """run stops where the test makes libvirt fail; the intent it recorded stays."""
        with self.assertRaises(Exception):
            self.run_job(op)
        op.refresh_from_db()
        return op

    def backup(self, op):
        return Backup.objects.get(uuid=op.intent["backup"])

    def test_a_shut_off_vm_is_copied_offline(self):
        op = self.submit()
        self.assertEqual(self.run_job(op), {"backup": op.intent["backup"]})
        prefix = f"vm1-{op.intent['backup']}"
        self.proxy.copy_disk_offline.assert_called_once_with(plan()["disks"][0], "b1", f"{prefix}-vda.qcow2", *_owner())
        self.proxy.begin_clone_backup.assert_not_called()
        self.assertEqual(self.written, [f"{prefix}-domain.xml", f"{prefix}-manifest.json"])  # the manifest last
        backup = self.backup(op)
        self.assertEqual((backup.state, backup.consistency, backup.instance), (Backup.READY, Backup.OFFLINE, self.vm))
        files = {f.role: f for f in backup.files.all()}
        self.assertEqual(set(files), {BackupFile.DISK, BackupFile.DOMAIN})
        self.assertEqual((files["disk"].dev, files["disk"].capacity, files["disk"].size), ("vda", GIB, GIB // 2))
        self.assertEqual(backup.manifest["left_out"], plan()["left_out"])
        self.assertEqual(backup.manifest["consistency"], "offline")
        self.assertEqual(backup.manifest["tpm"], "none")

    def test_a_shut_off_vms_tpm_state_is_kept(self):
        self.proxy.backup_plan.return_value = plan(tpm=True)
        op = self.submit()
        self.run_job(op)
        prefix = f"vm1-{op.intent['backup']}"
        self.assertEqual(self.written, [f"{prefix}-tpm-tpm2-00.permall", f"{prefix}-domain.xml", f"{prefix}-manifest.json"])
        self.assertEqual(self.modes[f"{prefix}-tpm-tpm2-00.permall"], "0600")  # a secret
        self.assertEqual(self.modes[f"{prefix}-domain.xml"], "0600")  # its graphics passwords
        tpm = self.backup(op).files.get(role=BackupFile.TPM)
        self.assertEqual((tpm.dev, tpm.volume, tpm.size, tpm.sha256), ("tpm2-00.permall", f"{prefix}-tpm-tpm2-00.permall", 5, "sha"))
        self.assertEqual(self.backup(op).manifest["tpm"], "copied")

    def test_a_tpm_that_never_started_is_said_so(self):
        self.proxy.backup_plan.return_value = plan(tpm=True)
        self.proxy.read_tpm.return_value = {}
        op = self.submit()
        self.run_job(op)
        self.assertEqual(self.backup(op).manifest["tpm"], "never written")
        self.assertFalse(self.backup(op).files.filter(role=BackupFile.TPM).exists())

    def test_a_failed_backup_removes_the_tpm_files_it_wrote(self):
        self.proxy.backup_plan.return_value = plan(tpm=True)
        op = self.submit()
        prefix = f"vm1-{op.intent['backup']}"
        self.pool.listVolumes.return_value = [f"{prefix}-tpm-tpm2-00.permall", "vm2-00000000-0000-4000-8000-000000000009-tpm-x"]
        self.fail_on = "-domain.xml"  # once the TPM file is written
        op = self.interrupted(op)
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.FAILED)
        self.assertIn(f"{prefix}-tpm-tpm2-00.permall", self.removed)
        self.assertNotIn("vm2-00000000-0000-4000-8000-000000000009-tpm-x", self.removed)

    def test_a_running_vm_is_frozen_backed_up_and_thawed(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        op = self.submit()
        self.run_job(op)
        calls = [c[0] for c in self.proxy.method_calls]
        self.assertLess(calls.index("fs_freeze"), calls.index("begin_clone_backup"))
        self.assertLess(calls.index("begin_clone_backup"), calls.index("fs_thaw"))
        self.assertEqual(self.backup(op).consistency, Backup.FROZEN)

    def test_no_agent_gives_crash_consistency_unless_frozen_is_required(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.is_agent_ready.return_value = False
        op = self.submit()
        self.run_job(op)
        self.proxy.fs_freeze.assert_not_called()
        self.assertEqual(self.backup(op).consistency, Backup.CRASH)
        with self.assertRaisesMessage(OperationError, "guest agent does not answer"):
            self.submit(frozen=True)

    def test_a_failed_freeze_goes_on_crash_consistent_unless_required(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.fs_freeze.side_effect = libvirt_error("agent timeout")
        op = self.submit()
        self.run_job(op)
        self.assertEqual(self.backup(op).consistency, Backup.CRASH)
        jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED))
        op = self.submit(frozen=True)
        self.interrupted(op)
        self.assertEqual(op.intent["copy_result"], [False, "agent timeout"])

    def test_frozen_is_refused_for_a_paused_vm(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_PAUSED
        with self.assertRaisesMessage(OperationError, "paused"):
            self.submit(frozen=True)
        op = self.submit()
        self.run_job(op)
        self.proxy.fs_freeze.assert_not_called()
        self.assertEqual(self.backup(op).consistency, Backup.CRASH)

    def test_a_failed_thaw_is_tried_again_while_the_copy_runs(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.fs_thaw.side_effect = [libvirt_error("thaw failed"), None]
        self.proxy.backup_progress.side_effect = [(1, 2), None]
        op = self.submit()
        result = self.run_job(op)
        self.assertNotIn("warning", result)
        self.assertEqual(self.proxy.fs_thaw.call_count, 2)
        op.refresh_from_db()
        self.assertFalse(op.intent["frozen"])

    def test_a_thaw_that_keeps_failing_is_left_to_recovery(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.fs_thaw.side_effect = libvirt_error("thaw failed")
        op = self.interrupted(self.submit())
        self.assertEqual(self.backup(op).state, Backup.READY)  # the copy is kept
        with self.assertRaises(libvirt.libvirtError):  # recovery waits and tries again
            CreateBackup().reconcile(op)
        self.proxy.fs_thaw.side_effect = None
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.SUCCEEDED)

    def test_a_cancelled_backup_of_a_guest_still_frozen_is_left_to_recovery(self):
        # the copy was aborted (cancel) while the thaw kept failing: recovery must thaw it, a cancel would not
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.fs_thaw.side_effect = libvirt_error("thaw failed")
        self.proxy.backup_result.return_value = (False, "operation aborted")
        op = self.submit(frozen=True)
        # the cancel comes while the copy runs
        self.proxy.begin_clone_backup.side_effect = lambda *a, **kw: Operation.objects.filter(pk=op.pk).update(
            cancel_requested=True)
        with self.assertRaises(OperationError):  # not Cancelled: the worker ends a cancelled job without recovery
            self.run_job(op)
        op.refresh_from_db()
        with self.assertRaises(libvirt.libvirtError):  # recovery thaws first, and tries again
            CreateBackup().reconcile(op)
        self.proxy.fs_thaw.side_effect = None
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.CANCELLED)

    def test_an_optional_freeze_that_failed_is_thawed_until_it_works(self):
        # a freeze that failed part way may have frozen some file systems: the guest counts as frozen
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.fs_freeze.side_effect = libvirt_error("agent timeout")
        self.proxy.fs_thaw.side_effect = [libvirt_error("agent busy"), None]
        self.proxy.backup_progress.side_effect = [(1, 2), None]
        op = self.submit()
        result = self.run_job(op)
        self.assertNotIn("warning", result)
        self.assertEqual(self.proxy.fs_thaw.call_count, 2)
        op.refresh_from_db()
        self.assertFalse(op.intent["frozen"])
        self.assertEqual(self.backup(op).consistency, Backup.CRASH)

    def test_a_running_vms_nvram_is_kept_when_it_did_not_change(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.backup_plan.return_value = plan(NVRAM)
        self.proxy.read_nvram.side_effect = [b"vars", b"new", b"vars"]  # before; after, changed then back
        op = self.submit()
        self.run_job(op)
        self.assertIn(f"vm1-{op.intent['backup']}-nvram.fd", self.written)
        self.assertEqual(self.backup(op).manifest["nvram"], "copied")

    def test_nvram_changed_across_the_copy_is_retried_then_refused(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.backup_plan.return_value = plan(NVRAM)
        counter = itertools.count()
        self.proxy.read_nvram.side_effect = lambda path: b"vars-%d" % next(counter)
        op = self.interrupted(self.submit())
        self.assertEqual(self.proxy.read_nvram.call_count, 4)  # before, then three after
        outcome = CreateBackup().reconcile(op)
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertIn(f"vm1-{op.intent['backup']}-vda.qcow2", self.removed)
        self.assertEqual(self.backup(op).state, Backup.FAILED)

    def test_the_guest_shutting_down_does_not_fail_the_backup(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING

        def progress():
            # the guest shuts down: its QEMU stays until the backup ends (PRESERVE_SHUTDOWN_DOMAIN)
            self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_SHUTOFF
            self.proxy.backup_progress.side_effect = None
            return (1, 2)

        self.proxy.backup_progress.side_effect = progress
        op = self.submit()
        self.run_job(op)
        self.assertEqual((self.backup(op).state, self.backup(op).consistency), (Backup.READY, Backup.FROZEN))

    def test_a_replaced_target_pool_is_refused_before_anything_is_made(self):
        op = self.submit()
        with patch("vmbackups.jobs.target_pool", side_effect=OperationError("Storage pool %(pool)s is replaced", pool="b1")):
            with self.assertRaisesMessage(OperationError, "Storage pool b1"):
                self.run_job(op)
        op.refresh_from_db()
        self.assertFalse(op.effects_started)
        self.assertFalse(Backup.objects.exists())
        self.proxy.copy_disk_offline.assert_not_called()
        self.proxy.make_live_targets.assert_not_called()

    def test_a_target_without_room_is_refused_before_anything_is_made(self):
        self.pool.info.return_value = [2, 100 * GIB, 0, GIB]
        op = self.submit()
        with self.assertRaisesMessage(OperationError, "the backup needs"):
            self.run_job(op)
        self.assertFalse(Backup.objects.exists())

    def test_a_full_target_fails_and_removes_the_volumes(self):
        self.proxy.copy_disk_offline.side_effect = libvirt_error("No space left on device")
        op = self.interrupted(self.submit())
        outcome = CreateBackup().reconcile(op)
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertIn("No space left on device", outcome.error[0]["text"])
        self.assertIn(f"vm1-{op.intent['backup']}-vda.qcow2", self.removed)
        self.assertEqual(self.backup(op).state, Backup.FAILED)

    def test_a_failed_push_backup_removes_the_volumes(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.backup_result.return_value = (False, "No space left on device")
        op = self.interrupted(self.submit())
        self.assertIn(f"vm1-{op.intent['backup']}-vda.qcow2", self.removed)
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.FAILED)

    def live_interrupted(self):
        """A push backup running when the worker stopped."""
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.backup_progress.side_effect = libvirt_error("connection lost")
        op = self.interrupted(self.submit())
        self.proxy.backup_progress.side_effect = None
        return op

    def test_recovery_watches_its_running_backup(self):
        op = self.live_interrupted()
        self.proxy.backup_targets.return_value = set(op.intent["paths"])
        self.proxy.backup_progress.return_value = (1, 4)
        outcome = CreateBackup().reconcile(op)
        self.assertEqual((outcome.state, outcome.progress), (Operation.RUNNING, (1, 4)))
        self.proxy.backup_targets.return_value = None
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.SUCCEEDED)
        self.assertEqual(self.backup(op).state, Backup.READY)

    def test_recovery_without_a_result_is_uncertain(self):
        op = self.live_interrupted()
        self.proxy.backup_result.return_value = None
        outcome = CreateBackup().reconcile(op)
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertIn(f"vm1-{op.intent['backup']}-vda.qcow2", outcome.error[0]["values"]["volumes"])
        self.assertEqual(self.removed, [])  # the files stay for the administrator
        self.assertEqual(self.backup(op).state, Backup.FAILED)

    def test_recovery_thaws_first(self):
        self.proxy.fs_thaw.side_effect = libvirt_error("thaw failed")
        op = self.live_interrupted()
        self.assertTrue(op.intent["frozen"])
        self.proxy.fs_thaw.side_effect = None
        self.proxy.method_calls.clear()
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.SUCCEEDED)
        calls = [c[0] for c in self.proxy.method_calls]
        self.assertLess(calls.index("fs_thaw"), calls.index("backup_targets"))

    def test_recovery_thaws_even_when_the_target_pool_is_gone(self):
        self.proxy.fs_thaw.side_effect = libvirt_error("thaw failed")
        op = self.live_interrupted()
        self.proxy.fs_thaw.side_effect = None
        self.proxy.fs_thaw.reset_mock()
        with patch("vmbackups.jobs.target_pool", side_effect=OperationError("Storage pool %(pool)s is gone", pool="b1")):
            with self.assertRaises(OperationError):
                CreateBackup().reconcile(op)
        self.proxy.fs_thaw.assert_called_once_with()

    def test_a_required_freeze_is_not_skipped_when_the_agent_goes(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        op = self.submit(frozen=True)
        # the run's check finds the agent; it is gone by the freeze
        self.proxy.is_agent_ready.side_effect = [True, False]
        self.proxy.fs_freeze.side_effect = libvirt_error("agent not connected")
        op = self.interrupted(op)
        self.proxy.begin_clone_backup.assert_not_called()
        self.assertEqual(op.intent["copy_result"], [False, "agent not connected"])

    def test_a_required_freeze_without_an_agent_at_the_start_makes_nothing(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        op = self.submit(frozen=True)
        self.proxy.is_agent_ready.return_value = False
        with self.assertRaisesMessage(OperationError, "guest agent does not answer"):
            self.run_job(op)
        self.assertFalse(Backup.objects.exists())

    def test_recovery_of_an_offline_copy_is_uncertain(self):
        self.proxy.copy_disk_offline.side_effect = RuntimeError("worker gone")  # no answer from libvirt
        op = self.interrupted(self.submit())
        outcome = CreateBackup().reconcile(op)
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertEqual(self.removed, [])

    def test_recovery_of_a_ready_backup_succeeds(self):
        op = self.submit()
        self.run_job(op)
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.SUCCEEDED)

    def test_cancel_aborts_then_removes(self):
        op = self.live_interrupted()
        self.proxy.backup_targets.return_value = set(op.intent["paths"])
        CreateBackup().cancel(op)
        self.proxy.abort_backup.assert_called_once_with()
        Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        op.refresh_from_db()
        self.proxy.backup_targets.return_value = None
        self.proxy.backup_result.return_value = (False, "operation aborted")
        self.assertEqual(CreateBackup().reconcile(op).state, Operation.CANCELLED)
        self.assertIn(f"vm1-{op.intent['backup']}-vda.qcow2", self.removed)

    def test_an_offline_copy_cancelled_stops_before_its_next_disk(self):
        op = self.submit()
        Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        with self.assertRaises(Cancelled):
            self.run_job(op)
        self.proxy.copy_disk_offline.assert_not_called()
        self.assertEqual(self.backup(op).state, Backup.FAILED)

    def test_an_offline_copy_cancelled_during_its_last_disk_is_not_kept(self):
        op = self.submit()
        self.proxy.copy_disk_offline.side_effect = lambda *a: Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        with self.assertRaises(Cancelled):
            self.run_job(op)
        self.assertEqual(self.written, [])
        self.assertIn(f"vm1-{op.intent['backup']}-vda.qcow2", self.removed)
        self.assertEqual(self.backup(op).state, Backup.FAILED)

    def test_a_vm_started_during_its_offline_copy_is_not_published(self):
        # its NVRAM and TPM state would be newer than the disks copied
        started = lambda *a: setattr(self.proxy.get_status, "return_value", libvirt.VIR_DOMAIN_RUNNING)  # noqa: E731
        self.proxy.copy_disk_offline.side_effect = started
        op = self.interrupted(self.submit())
        self.assertEqual(self.written, [])
        outcome = CreateBackup().reconcile(op)  # recovery does not publish it either
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertIn("started", str(outcome.error))
        self.assertIn(f"vm1-{op.intent['backup']}-vda.qcow2", self.removed)
        self.assertEqual(self.backup(op).state, Backup.FAILED)

    def test_progress_counts_the_copied_disks(self):
        op = self.submit()
        self.run_job(op)
        op.refresh_from_db()
        self.assertEqual(CreateBackup().progress(op), (GIB, GIB))

    def test_a_schedules_backup_is_linked_to_it_unless_it_was_deleted(self):
        import datetime

        from vmbackups.models import BackupPolicy

        policy = BackupPolicy.objects.create(name="nightly", target=self.target, time=datetime.time(2), keep=2,
                                             owner=self.admin)
        op = jobs.submit("backup.create", self.admin, {"instance": self.vm.pk, "target": self.target.pk,
                                                       "policy": policy.pk}, "key-policy-0001")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        self.run_job(op)
        self.assertEqual(self.backup(op).policy, policy)
        jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED))
        policy_pk = policy.pk
        policy.delete()  # while the next one is queued
        op = jobs.submit("backup.create", self.admin, {"instance": self.vm.pk, "target": self.target.pk,
                                                       "policy": policy_pk}, "key-policy-0002")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        self.run_job(op)
        self.assertIsNone(self.backup(op).policy)

    def chain(self, full_every=3, links=1):
        """A schedule whose last backups of the VM form a chain of links points."""
        import datetime

        from vmbackups.models import BackupPolicy

        self.policy = BackupPolicy.objects.create(name="nightly", target=self.target, time=datetime.time(2), keep=7,
                                                  full_every=full_every, owner=self.admin)
        parent = None
        for _n in range(links):
            parent = Backup.objects.create(target=self.target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                           compute_name="h1", state=Backup.READY, policy=self.policy, parent=parent)
            parent.checkpoint = f"wvc-{parent.uuid}"
            parent.save()
            BackupFile.objects.create(backup=parent, role=BackupFile.DISK, dev="vda", volume=f"{parent.prefix}-vda.qcow2",
                                      format="qcow2", capacity=GIB)
        self.pool.listVolumes.return_value = [f.volume for f in BackupFile.objects.all()]
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.proxy.checkpoint_sizes.return_value = {"vda": MIB}
        return parent

    def scheduled(self):
        op = jobs.submit("backup.create", self.admin, {"instance": self.vm.pk, "target": self.target.pk,
                                                       "policy": self.policy.pk}, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op

    def test_a_schedules_backup_builds_on_its_last_one(self):
        parent = self.chain()
        op = self.scheduled()
        self.run_job(op)
        backup = self.backup(op)
        self.assertEqual((backup.parent, backup.checkpoint), (parent, f"wvc-{backup.uuid}"))
        self.assertEqual(self.proxy.make_live_targets.call_args.kwargs["backing"], {"vda": f"{parent.prefix}-vda.qcow2"})
        self.assertEqual(self.proxy.begin_clone_backup.call_args.kwargs,
                         {"incremental": parent.checkpoint, "checkpoint": backup.checkpoint})
        self.proxy.checkpoint_sizes.assert_called_with(parent.checkpoint, ["vda"])
        self.assertEqual((backup.manifest["parent"], backup.manifest["checkpoint"]), (str(parent.uuid), backup.checkpoint))
        # the checkpoints pruned before the backup began: the anchor stays
        keep = self.proxy.prune_checkpoints.call_args.kwargs["keep"]
        self.assertEqual(keep, {parent.checkpoint})
        self.assertIn(parent.checkpoint, self.proxy.prune_checkpoints.call_args.kwargs["known"])

    def test_an_incremental_backup_needs_room_for_the_changed_data_only(self):
        parent = self.chain()
        self.pool.info.return_value = [2, 100 * GIB, 0, GIB + GIB // 2]  # less than the disk's capacity and margin
        op = self.scheduled()
        self.run_job(op)
        self.assertEqual(self.backup(op).parent, parent)
        from operations.models import Claim

        Claim.objects.all().delete()
        self.proxy.checkpoint_sizes.return_value = None  # a full backup then: it needs the disk's capacity
        with self.assertRaisesMessage(OperationError, "the backup needs"):
            self.run_job(self.scheduled())

    def test_a_chain_as_long_as_full_every_starts_again(self):
        self.chain(full_every=3, links=3)
        op = self.scheduled()
        self.run_job(op)
        backup = self.backup(op)
        self.assertIsNone(backup.parent)
        self.assertEqual(backup.checkpoint, f"wvc-{backup.uuid}")  # the next one builds on it
        self.assertEqual(self.proxy.begin_clone_backup.call_args.kwargs, {"incremental": None, "checkpoint": backup.checkpoint})
        self.assertEqual(self.proxy.make_live_targets.call_args.kwargs["backing"], {})

    def test_a_base_that_cannot_be_used_gives_a_full_backup(self):
        for name, broken in (
            ("lost bitmap", lambda: setattr(self.proxy.checkpoint_sizes, "return_value", None)),
            ("file gone", lambda: setattr(self.pool.listVolumes, "return_value", [])),
            ("disk added", lambda: self.proxy.backup_plan.return_value["disks"].append(
                {"dev": "vdb", "path": "/pool/b.qcow2", "pool": "default", "format": "qcow2", "capacity": GIB})),
        ):
            with self.subTest(name):
                Backup.objects.all().delete()
                from vmbackups.models import BackupPolicy

                BackupPolicy.objects.all().delete()
                self.proxy.backup_plan.return_value = plan()
                self.chain()
                broken()
                Operation.objects.update(state=Operation.SUCCEEDED)
                from operations.models import Claim

                Claim.objects.all().delete()
                op = self.scheduled()
                self.run_job(op)
                self.assertIsNone(self.backup(op).parent)

    def test_full_every_one_and_backups_by_hand_make_no_checkpoint(self):
        self.chain(full_every=1)
        op = self.scheduled()
        self.run_job(op)
        self.assertEqual((self.backup(op).parent, self.backup(op).checkpoint), (None, ""))
        self.assertEqual(self.proxy.begin_clone_backup.call_args.kwargs, {"incremental": None, "checkpoint": None})
        # a schedule changed to full backups only: the checkpoints it left go
        self.assertEqual(self.proxy.prune_checkpoints.call_args.kwargs["keep"], set())

    def test_a_raw_disk_or_a_shut_off_vm_makes_no_checkpoint(self):
        self.chain()
        self.proxy.backup_plan.return_value["disks"][0]["format"] = "raw"  # no bitmaps in a raw file
        op = self.scheduled()
        self.run_job(op)
        self.assertEqual(self.backup(op).checkpoint, "")

    def test_the_log_names_the_target_and_consistency(self):
        op = self.submit()
        self.run_job(op)
        op.refresh_from_db()
        self.assertEqual(CreateBackup().log_entry(op, Operation.SUCCEEDED)[3], "VM vm1: backed up to nfs1 (offline)")

    def test_a_vm_on_a_host_without_the_target_is_refused(self):
        other = Compute.objects.create(name="h2", hostname="192.0.2.22", login="u", password="p", type=1)
        Instance.objects.filter(pk=self.vm.pk).update(compute=other)
        with self.assertRaisesMessage(OperationError, "has no storage pool on h2"):
            self.submit()


class BackupTabTests(PageControls, TransactionTestCase):
    def test_the_tab_lists_backups_and_says_why_not(self):
        admin = get_user_model().objects.create_superuser("tab-admin", "a@example.com", "x")
        target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=target, compute=self.compute, pool="b1", pool_uuid="u")
        Backup.objects.create(target=target, instance=self.instance, vm_uuid=self.instance.uuid, vm_name="ctl-vm",
                              compute_name="ctl-compute", state=Backup.READY, consistency=Backup.FROZEN, size=3 * GIB)
        with patch("vmbackups.utils.wvmBackup") as backup_proxy:
            self.controls(admin)
            page = lxml_html.fromstring(self.last_page)
            self.assertTrue(page.xpath("//div[@id='backups']//form[contains(@action, '/backups/vm/')]"))
            self.assertIn("nfs1", page.xpath("string(//select[@id='backup-target'])"))
            self.assertIn("3\xa0GiB", page.xpath("string(//div[@id='backups']//table)"))
            backup_proxy.return_value.backup_plan.side_effect = OperationError("%(vm)s has TPM state", vm="ctl-vm")
            self.controls(admin)
            page = lxml_html.fromstring(self.last_page)
            self.assertIn("ctl-vm has TPM state", page.xpath("string(//div[@id='backups'])"))
            self.assertFalse(page.xpath("//div[@id='backups']//form[contains(@action, '/create/')]"))

    def test_an_owner_gets_no_link_to_a_job_they_cannot_open(self):
        owner = self.user("tab-owner3", perms=("backup_instances",), owner={"is_change": True})
        target = BackupTarget.objects.create(name="opened2", owners=True)
        BackupTargetPool.objects.create(target=target, compute=self.compute, pool="p", pool_uuid="u")
        admin = get_user_model().objects.create_superuser("tab-admin3", "c@example.com", "x")
        from operations.models import Operation as Op

        theirs = Op.objects.create(kind="backup.create", user=admin, state=Op.FAILED, params={}, intent={})
        Backup.objects.create(target=target, instance=self.instance, vm_uuid=self.instance.uuid, vm_name="ctl-vm",
                              compute_name="ctl-compute", state=Backup.FAILED, operation=theirs)
        with patch("vmbackups.utils.wvmBackup"):
            self.controls(owner)
        tab = lxml_html.fromstring(self.last_page).xpath("//div[@id='backups']")[0]
        self.assertFalse(tab.xpath(".//a[contains(@href, '/jobs/')]"))

    def test_owners_without_the_backup_permission_have_no_backups_tab(self):
        self.controls(self.user("tab-owner", owner={"is_change": True}))
        self.assertFalse(lxml_html.fromstring(self.last_page).xpath("//*[@id='backups']"))
        self.controls(self.user("tab-viewer", perms=("backup_instances",), owner={"is_change": False}))
        self.assertFalse(lxml_html.fromstring(self.last_page).xpath("//*[@id='backups']"))

    def test_an_owner_sees_targets_open_to_owners_and_deletes_only_their_own(self):
        import datetime

        from vmbackups.models import BackupPolicy

        owner = self.user("tab-owner2", perms=("backup_instances",), owner={"is_change": True})
        closed = BackupTarget.objects.create(name="closed")
        opened = BackupTarget.objects.create(name="opened", owners=True)
        for target in (closed, opened):
            BackupTargetPool.objects.create(target=target, compute=self.compute, pool=target.name, pool_uuid="u")
        policy = BackupPolicy.objects.create(name="nightly", target=opened, time=datetime.time(2), keep=2)
        policy.instances.add(self.instance)

        def backup(target, **fields):
            return Backup.objects.create(target=target, instance=self.instance, vm_uuid=self.instance.uuid,
                                         vm_name="ctl-vm", compute_name="ctl-compute", state=Backup.READY, **fields)

        hidden, mine, scheduled = backup(closed), backup(opened, taken_by=owner), backup(opened, policy=policy)
        with patch("vmbackups.utils.wvmBackup"):
            self.controls(owner)
        tab = lxml_html.fromstring(self.last_page).xpath("//div[@id='backups']")[0]
        self.assertEqual(tab.xpath(".//select[@id='backup-target']/option/text()"), ["opened"])
        self.assertNotIn("nightly", tab.text_content())  # schedules are the administrators'
        actions = tab.xpath(".//form[contains(@action, '/delete/')]/@action")
        self.assertEqual(actions, [f"/backups/{mine.uuid}/delete/"])
        self.assertTrue(tab.xpath(f".//a[@href='/backups/{scheduled.uuid}/restore-over/']"))
        self.assertFalse(tab.xpath(".//a[contains(@href, '/restore-disk/')]"))
        self.assertNotIn(str(hidden.uuid), lxml_html.tostring(tab).decode())


class BackupApiTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("api_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.21", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="21212121-0000-4000-8000-000000000001")
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u")

    @patch("vmbackups.jobs.wvmBackup")
    def test_api_post_returns_the_job(self, backup_proxy):
        backup_proxy.return_value = proxy()
        self.client.force_login(self.admin)
        response = self.client.post("/api/v1/backups/", {"instance": self.vm.pk, "target": self.target.pk,
                                                          "submission_key": "key-api-0001"}, content_type="application/json")
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["kind"], "backup.create")
        backup = Backup.objects.create(target=self.target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                       compute_name="h1", state=Backup.READY)
        listed = self.client.get("/api/v1/backups/").json()
        rows = listed["results"] if isinstance(listed, dict) else listed
        self.assertEqual([r["uuid"] for r in rows], [str(backup.uuid)])
        self.assertEqual(self.client.get(f"/api/v1/backups/{backup.uuid}/").json()["target"], "nfs1")

    def test_api_is_superuser_only(self):
        user = get_user_model().objects.create_user("api_user", password="pw")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/api/v1/backups/").status_code, 403)
        response = self.client.post("/api/v1/backups/", {"instance": self.vm.pk, "target": self.target.pk,
                                                          "submission_key": "key-api-0002"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
