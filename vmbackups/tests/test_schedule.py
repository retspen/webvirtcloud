"""Backup schedules: the worker's periodic pass submits each VM's backup once
a day within its window, deletes what is beyond keep, checks targets."""

import datetime
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import libvirt
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from django.utils import timezone, translation

from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from operations import jobs
from operations.jobs import Context
from operations.models import Operation, acquire
from operations.utils import words
from vmbackups import schedule
from vmbackups.jobs import CheckTarget, DeleteBackup, _beyond_keep
from vmbackups.models import Backup, BackupFile, BackupPolicy, BackupRun, BackupTarget, BackupTargetPool
from vrtManager.util import OperationError

UTC = datetime.timezone.utc
WORKER = "wvc-test:1:a"


def at(*args):
    return datetime.datetime(*args, tzinfo=UTC)


class Inline:
    """The pool of per-compute tasks, run at once; pending: computes whose task still runs;
    queued: tasks held until run_queued (busy threads)."""

    def __init__(self):
        self.pending = set()
        self.hold = False
        self.queued = []

    def submit(self, fn, compute_id, items):
        future = Future()
        if compute_id in self.pending:
            return future  # never done: a hung host
        if self.hold:
            self.queued.append((fn, compute_id, items, future))
            return future
        fn(compute_id, items)
        future.set_result(None)
        return future

    def run_queued(self, now):
        with patch("django.utils.timezone.now", return_value=now):
            for fn, compute_id, items, future in self.queued:
                fn(compute_id, items)
                future.set_result(None)


def proxy():
    p = MagicMock()
    p.get_status.return_value = libvirt.VIR_DOMAIN_SHUTOFF
    p.backup_plan.return_value = {"definition": "<domain/>", "disks": [], "nvram": None, "left_out": []}
    return p


@override_settings(TIME_ZONE="UTC")
class ScheduleTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("sc_admin", "a@example.com", "pw")
        self.c1 = Compute.objects.create(name="h1", hostname="192.0.2.71", login="u", password="p", type=1)
        self.c2 = Compute.objects.create(name="h2", hostname="192.0.2.72", login="u", password="p", type=1)
        self.vm1 = Instance.objects.create(compute=self.c1, name="vm1", uuid="71717171-0000-4000-8000-000000000001")
        self.vm2 = Instance.objects.create(compute=self.c1, name="vm2", uuid="71717171-0000-4000-8000-000000000002")
        self.target = BackupTarget.objects.create(name="nfs1", checked_at=at(2026, 11, 17, 0, 0))
        BackupTargetPool.objects.create(target=self.target, compute=self.c1, pool="b1", pool_uuid="u")
        BackupTargetPool.objects.create(target=self.target, compute=self.c2, pool="b1", pool_uuid="u")
        self.policy = BackupPolicy.objects.create(name="nightly", target=self.target, time=datetime.time(2, 0), keep=2,
                                                  owner=self.admin)
        BackupPolicy.objects.filter(pk=self.policy.pk).update(created_at=at(2026, 11, 17))
        self.policy.refresh_from_db()
        self.policy.instances.add(self.vm1)
        self.pool = Inline()
        self.proxy = proxy()
        target_pool = MagicMock()
        target_pool.info.return_value = [2, 1 << 40, 0, 1 << 40]
        for name, value in (("vmbackups.schedule._pool", self.pool),
                            ("vmbackups.schedule._tasks", {}),
                            ("vmbackups.jobs.wvmBackup", MagicMock(return_value=self.proxy)),
                            ("vmbackups.jobs.target_pool", MagicMock(return_value=target_pool))):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def pass_at(self, now):
        """A pass of the worker at now, its tasks run then too."""
        with patch("django.utils.timezone.now", return_value=now):
            schedule.run_schedules(now)

    def creates(self):
        return list(Operation.objects.filter(kind="backup.create").order_by("created_at"))

    def finish_all(self):
        for op in Operation.objects.filter(state__in=Operation.ACTIVE):
            jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED))

    def test_due_at_its_time_not_before(self):
        self.pass_at(at(2026, 11, 17, 1, 59))
        self.assertEqual(self.creates(), [])
        self.pass_at(at(2026, 11, 17, 2, 0))
        op = self.creates()[0]
        self.assertEqual(op.params, {"instance": self.vm1.pk, "target": self.target.pk, "frozen": False,
                                     "policy": self.policy.pk, "deadline": "2026-11-17T08:00:00+00:00"})
        self.assertEqual(op.username, "sc_admin")
        run = BackupRun.objects.get()
        self.assertEqual((run.instance, run.day, run.state, run.operation), (self.vm1, datetime.date(2026, 11, 17),
                                                                            BackupRun.SUBMITTED, op))

    def test_a_backup_that_waited_past_its_window_does_not_start(self):
        from operations.jobs import Context
        from vmbackups.jobs import CreateBackup

        self.pass_at(at(2026, 11, 17, 7, 59))
        op = self.creates()[0]
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        with patch("django.utils.timezone.now", return_value=at(2026, 11, 17, 8, 1)):  # it waited for a slot
            with self.assertRaisesMessage(OperationError, "window ended"):
                CreateBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))
        self.assertFalse(Backup.objects.exists())
        self.proxy.copy_disk_offline.assert_not_called()

    def started(self, now, op):
        from operations.jobs import Context
        from vmbackups.jobs import CreateBackup

        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        with patch("django.utils.timezone.now", return_value=now):
            CreateBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def test_a_scheduled_backup_whose_host_went_into_maintenance_does_not_start(self):
        self.pass_at(at(2026, 11, 17, 2, 0))
        Compute.objects.filter(pk=self.c1.pk).update(maintenance_since=at(2026, 11, 17, 2, 1))
        with self.assertRaisesMessage(OperationError, "maintenance"):
            self.started(at(2026, 11, 17, 2, 2), self.creates()[0])
        self.assertFalse(Backup.objects.exists())

    def test_the_window_is_checked_again_after_the_host_answered(self):
        self.pass_at(at(2026, 11, 17, 7, 59))
        # the host answers the checks only after the window ended
        self.proxy.backup_plan.side_effect = lambda: patch_now.start() or {
            "definition": "<domain/>", "disks": [], "nvram": None, "left_out": []}
        patch_now = patch("django.utils.timezone.now", return_value=at(2026, 11, 17, 8, 30))
        self.addCleanup(patch.stopall)
        with self.assertRaisesMessage(OperationError, "window ended"):
            self.started(at(2026, 11, 17, 7, 59, 30), self.creates()[0])
        self.assertFalse(Backup.objects.exists())

    def test_once_a_day(self):
        self.pass_at(at(2026, 11, 17, 2, 0))
        self.finish_all()
        self.pass_at(at(2026, 11, 17, 3, 0))
        self.assertEqual(len(self.creates()), 1)
        self.pass_at(at(2026, 11, 18, 2, 1))
        self.assertEqual(len(self.creates()), 2)

    def test_a_worker_stopped_between_the_job_and_its_run_row_submits_no_second_job(self):
        self.pass_at(at(2026, 11, 17, 2, 0))
        BackupRun.objects.all().delete()  # the row was never written
        self.pass_at(at(2026, 11, 17, 2, 1))
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(BackupRun.objects.get().operation, self.creates()[0])

    def test_a_busy_target_is_tried_again_and_the_vms_go_one_after_another(self):
        self.policy.instances.add(self.vm2)
        self.pass_at(at(2026, 11, 17, 2, 0))
        self.assertEqual(BackupRun.objects.count(), 1)  # the target admits one copy
        self.pass_at(at(2026, 11, 17, 2, 1))
        self.assertEqual(BackupRun.objects.count(), 1)  # still busy
        self.finish_all()
        self.pass_at(at(2026, 11, 17, 2, 30))
        self.assertEqual(BackupRun.objects.count(), 2)

    def test_a_host_in_maintenance_is_deferred_then_skipped(self):
        Compute.objects.filter(pk=self.c1.pk).update(maintenance_since=at(2026, 11, 16))
        self.pass_at(at(2026, 11, 17, 2, 0))
        self.assertEqual(BackupRun.objects.count(), 0)
        self.pass_at(at(2026, 11, 17, 8, 1))
        run = BackupRun.objects.get()
        self.assertEqual(run.state, BackupRun.SKIPPED)
        self.assertIn("maintenance", words(run.note))
        self.assertEqual(self.creates(), [])

    def test_maintenance_ended_inside_the_window(self):
        Compute.objects.filter(pk=self.c1.pk).update(maintenance_since=at(2026, 11, 16))
        self.pass_at(at(2026, 11, 17, 2, 0))
        Compute.objects.filter(pk=self.c1.pk).update(maintenance_since=None)
        self.pass_at(at(2026, 11, 17, 4, 0))
        self.assertEqual(BackupRun.objects.get().state, BackupRun.SUBMITTED)

    def test_a_day_the_worker_was_down_is_skipped_not_caught_up(self):
        self.pass_at(at(2026, 11, 18, 9, 0))  # down from before 02:00 on the 17th
        self.assertEqual(sorted(BackupRun.objects.values_list("day", "state")),
                         [(datetime.date(2026, 11, 17), BackupRun.SKIPPED), (datetime.date(2026, 11, 18), BackupRun.SKIPPED)])
        self.assertEqual(self.creates(), [])

    def test_a_run_not_started_in_its_window_is_skipped(self):
        self.pass_at(at(2026, 11, 17, 8, 1))  # the worker was down from before 02:00
        run = BackupRun.objects.get()
        self.assertEqual(run.state, BackupRun.SKIPPED)
        self.assertIn("6 hours", words(run.note))
        self.assertEqual(self.creates(), [])

    def test_a_new_schedule_does_not_skip_the_times_before_it(self):
        BackupPolicy.objects.filter(pk=self.policy.pk).update(created_at=at(2026, 11, 17, 10))
        self.pass_at(at(2026, 11, 17, 10, 1))
        self.assertEqual(BackupRun.objects.count(), 0)
        self.pass_at(at(2026, 11, 18, 2, 0))
        self.assertEqual(BackupRun.objects.get().day, datetime.date(2026, 11, 18))

    def test_a_late_schedule_still_runs_after_midnight(self):
        BackupPolicy.objects.filter(pk=self.policy.pk).update(time=datetime.time(23, 0))
        self.pass_at(at(2026, 11, 18, 1, 0))  # the worker came back after midnight
        self.assertEqual(BackupRun.objects.get().day, datetime.date(2026, 11, 17))
        self.assertEqual(len(self.creates()), 1)

    def test_a_task_that_waited_for_a_thread_checks_again_before_it_submits(self):
        self.pool.hold = True
        self.pass_at(at(2026, 11, 17, 2, 0))
        BackupPolicy.objects.filter(pk=self.policy.pk).update(enabled=False)
        self.pool.run_queued(at(2026, 11, 17, 2, 5))
        self.assertEqual(self.creates(), [])
        BackupPolicy.objects.filter(pk=self.policy.pk).update(enabled=True)
        self.pool.queued.clear()
        self.pass_at(at(2026, 11, 17, 7, 59))
        self.pool.run_queued(at(2026, 11, 17, 8, 1))  # its window ended while it waited
        self.assertEqual(self.creates(), [])

    def test_a_task_that_waited_while_the_time_was_moved_does_not_submit(self):
        self.pool.hold = True
        self.pass_at(at(2026, 11, 17, 2, 0))
        BackupPolicy.objects.filter(pk=self.policy.pk).update(time=datetime.time(5, 0))
        self.pool.run_queued(at(2026, 11, 17, 2, 1))
        self.assertEqual(self.creates(), [])
        self.assertEqual(BackupRun.objects.count(), 0)

    def test_the_target_jobs_hold_the_targets_computes(self):
        from operations.models import Claim

        BackupTarget.objects.filter(pk=self.target.pk).update(checked_at=at(2026, 11, 16))
        schedule.check_targets(at(2026, 11, 17, 9))
        op = Operation.objects.get(kind="backup.check")
        # the worker counts a job's hosts by these: a hung host takes no more than its share of the slots
        self.assertEqual(set(Claim.objects.filter(operation=op, resource__startswith="compute:")
                             .values_list("resource", "mode")),
                         {(f"compute:{self.c1.pk}", Claim.SHARED), (f"compute:{self.c2.pk}", Claim.SHARED)})
        for backup in self.backups(*[Backup.READY] * 3):
            pass
        jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED))
        schedule.retain()
        delete = Operation.objects.get(kind="backup.delete")
        self.assertTrue(Claim.objects.filter(operation=delete, resource=f"compute:{self.c1.pk}").exists())

    def test_an_owner_who_is_no_superuser_fails_the_run(self):
        get_user_model().objects.filter(pk=self.admin.pk).update(is_superuser=False)
        self.pass_at(at(2026, 11, 17, 2, 0))
        run = BackupRun.objects.get()
        self.assertEqual(run.state, BackupRun.FAILED)
        self.assertIn("owner", words(run.note))

    def test_a_vm_that_cannot_be_backed_up_fails_once_with_the_reason(self):
        self.proxy.backup_plan.side_effect = OperationError("%(vm)s has TPM state; shut it down to back it up", vm="vm1")
        self.pass_at(at(2026, 11, 17, 2, 0))
        self.pass_at(at(2026, 11, 17, 2, 1))
        run = BackupRun.objects.get()
        self.assertEqual((run.state, words(run.note)), (BackupRun.FAILED, "vm1 has TPM state; shut it down to back it up"))
        with translation.override("tr"):  # in the reader's language, its values in place
            self.assertEqual(words(run.note), "vm1 TPM durumu taşıyor; yedeklemek için kapatın")

    def test_an_unreachable_host_is_tried_again(self):
        from vrtManager.util import ConnectionFailed

        with patch("vmbackups.jobs.wvmBackup", side_effect=ConnectionFailed("Cannot connect to %(host)s", host="h1")):
            self.pass_at(at(2026, 11, 17, 2, 0))
        self.assertEqual(BackupRun.objects.count(), 0)
        self.pass_at(at(2026, 11, 17, 2, 1))
        self.assertEqual(BackupRun.objects.get().state, BackupRun.SUBMITTED)

    def test_a_compute_schedule_takes_its_vms_now(self):
        whole = BackupPolicy.objects.create(name="host", target=self.target, compute=self.c1, time=datetime.time(3),
                                            keep=1, owner=self.admin)
        BackupPolicy.objects.filter(pk=whole.pk).update(created_at=at(2026, 11, 17))
        BackupPolicy.objects.filter(pk=self.policy.pk).update(enabled=False)
        self.pass_at(at(2026, 11, 17, 3, 0))
        self.finish_all()
        self.pass_at(at(2026, 11, 17, 3, 1))
        self.assertEqual(sorted(BackupRun.objects.values_list("instance__name", flat=True)), ["vm1", "vm2"])

    def test_a_hung_host_stops_no_other_hosts_schedule(self):
        vm3 = Instance.objects.create(compute=self.c2, name="vm3", uuid="71717171-0000-4000-8000-000000000003")
        other = BackupTarget.objects.create(name="nfs2", checked_at=at(2026, 11, 17))
        BackupTargetPool.objects.create(target=other, compute=self.c2, pool="b2", pool_uuid="u2")
        policy = BackupPolicy.objects.create(name="other", target=other, time=datetime.time(2), keep=1, owner=self.admin)
        BackupPolicy.objects.filter(pk=policy.pk).update(created_at=at(2026, 11, 17))
        policy.instances.add(vm3)
        self.pool.pending.add(self.c1.pk)  # its first task never ends
        self.pass_at(at(2026, 11, 17, 2, 0))
        self.pass_at(at(2026, 11, 17, 2, 1))
        self.assertEqual(list(BackupRun.objects.values_list("instance__name", flat=True)), ["vm3"])

    @override_settings(TIME_ZONE="Europe/Berlin")
    def test_a_time_in_the_spring_forward_gap_runs_an_hour_later_once(self):
        BackupPolicy.objects.filter(pk=self.policy.pk).update(time=datetime.time(2, 30), created_at=at(2026, 3, 29))
        # 2026-03-29 02:30 does not exist in Berlin: 03:30 local, 01:30 UTC
        self.pass_at(at(2026, 3, 29, 1, 29))
        self.assertEqual(BackupRun.objects.count(), 0)
        self.pass_at(at(2026, 3, 29, 1, 31))
        self.assertEqual(BackupRun.objects.get().day, datetime.date(2026, 3, 29))

    @override_settings(TIME_ZONE="Europe/Berlin")
    def test_the_window_is_six_real_hours_on_a_clock_change_day(self):
        BackupPolicy.objects.filter(pk=self.policy.pk).update(time=datetime.time(2, 30), created_at=at(2026, 3, 29))
        self.pass_at(at(2026, 3, 29, 7, 0))  # 5.5 h after 01:30 UTC
        self.assertEqual(BackupRun.objects.get().state, BackupRun.SUBMITTED)

    def test_the_schedule_pool_has_a_thread_for_each_compute(self):
        self.assertGreaterEqual(schedule.THREADS, 32)

    @override_settings(TIME_ZONE="Europe/Berlin")
    def test_a_time_repeated_in_autumn_runs_once(self):
        BackupPolicy.objects.filter(pk=self.policy.pk).update(time=datetime.time(2, 30), created_at=at(2026, 10, 25))
        # 2026-10-25 02:30 is 00:30 and 01:30 UTC; the first is the schedule's
        self.pass_at(at(2026, 10, 25, 0, 31))
        self.finish_all()
        self.pass_at(at(2026, 10, 25, 1, 31))
        self.assertEqual(len(self.creates()), 1)

    # -- retention -------------------------------------------------------

    def backups(self, *states, policy=True, instance=None):
        made = []
        for number, state in enumerate(states):
            b = Backup.objects.create(target=self.target, instance=instance or self.vm1, vm_uuid=self.vm1.uuid,
                                      vm_name="vm1", compute_name="h1", state=state,
                                      policy=self.policy if policy else None)
            Backup.objects.filter(pk=b.pk).update(created_at=at(2026, 11, 10 + number))
            made.append(b)
        return made

    def deletes(self):
        return list(Operation.objects.filter(kind="backup.delete").order_by("created_at"))

    def test_retention_deletes_the_oldest_beyond_keep_one_at_a_time(self):
        oldest, older, _new, _newest = self.backups(*[Backup.READY] * 4)
        schedule.retain()
        (op,) = self.deletes()
        self.assertEqual(op.params, {"backup": str(oldest.uuid), "retention": self.policy.pk})
        schedule.retain()  # the target is busy with that deletion
        self.assertEqual(len(self.deletes()), 1)
        self.finish_all()
        Backup.objects.filter(pk=oldest.pk).delete()
        schedule.retain()
        self.assertEqual(self.deletes()[-1].params["backup"], str(older.uuid))

    def test_retention_reads_each_vm_once(self):
        self.backups(*[Backup.READY] * 4)
        with patch("vmbackups.schedule.beyond_keep", return_value=[]) as beyond:
            schedule.retain()
        self.assertEqual(beyond.call_count, 1)

    def chained(self, *backups):
        for parent, child in zip(backups, backups[1:]):
            Backup.objects.filter(pk=child.pk).update(parent=parent)

    def test_retention_deletes_a_chain_only_when_all_of_it_is_beyond_keep(self):
        # keep 2: a full, two incrementals on it, then a new full
        full, inc1, inc2, _new = self.backups(*[Backup.READY] * 4)
        self.chained(full, inc1, inc2)
        schedule.retain()  # inc2 is kept, and inc1 and full are its base
        self.assertEqual(self.deletes(), [])
        (newest,) = self.backups(Backup.READY)  # one more: inc2 is beyond keep too, and a leaf
        Backup.objects.filter(pk=newest.pk).update(created_at=at(2026, 11, 20))
        schedule.retain()
        self.assertEqual(self.deletes()[-1].params["backup"], str(inc2.uuid))  # newest first: each one a leaf

    def test_a_failed_incremental_does_not_pin_its_base(self):
        oldest, _a, _b = self.backups(*[Backup.READY] * 3)
        (failed,) = self.backups(Backup.FAILED)
        Backup.objects.filter(pk=failed.pk).update(parent=oldest)
        schedule.retain()
        self.assertEqual(self.deletes()[-1].params["backup"], str(oldest.uuid))

    def test_a_failed_deletion_is_tried_again_an_hour_later(self):
        oldest, *_rest = self.backups(*[Backup.READY] * 3)
        schedule.retain()
        (op,) = self.deletes()
        jobs.finish(op, jobs.Outcome(Operation.FAILED))
        schedule.retain()
        self.assertEqual(len(self.deletes()), 1)  # not every minute
        Operation.objects.filter(pk=op.pk).update(finished_at=op.finished_at - datetime.timedelta(minutes=61))
        schedule.retain()
        self.assertEqual(len(self.deletes()), 2)
        self.assertEqual(self.deletes()[-1].params["backup"], str(oldest.uuid))

    def test_a_missing_incremental_goes_with_its_chain(self):
        # keep 2: a full and an incremental on it whose files are lost, then two new fulls
        full, inc, new, newest = self.backups(Backup.READY, Backup.MISSING, Backup.READY, Backup.READY)
        self.chained(full, inc)
        schedule.retain()
        (op,) = self.deletes()
        self.assertEqual(op.params["backup"], str(inc.uuid))
        self.assertTrue(_beyond_keep(inc, self.policy.pk))
        self.finish_all()
        Backup.objects.filter(pk=inc.pk).delete()
        schedule.retain()
        self.assertEqual(self.deletes()[-1].params["backup"], str(full.uuid))

    def test_a_missing_backup_does_not_count_in_keep(self):
        oldest, _missing, _newest = self.backups(Backup.READY, Backup.MISSING, Backup.READY)
        schedule.retain()
        self.assertEqual(self.deletes(), [])

    def test_retention_keeps_keep_ready_backups_when_the_newest_failed(self):
        self.backups(Backup.READY, Backup.READY, Backup.FAILED)
        schedule.retain()
        self.assertEqual(self.deletes(), [])

    def test_retention_leaves_backups_by_hand_and_of_removed_vms(self):
        self.backups(Backup.READY, Backup.READY, policy=False)
        self.backups(Backup.READY, Backup.READY, Backup.READY)
        Backup.objects.filter(policy=self.policy).update(instance=None)  # the VM row is gone
        schedule.retain()
        self.assertEqual(self.deletes(), [])

    def run_delete(self, backup):
        op = jobs.submit("backup.delete", self.admin, {"backup": str(backup.uuid), "retention": self.policy.pk},
                         "key-retain-0001")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op, Context(op, SimpleNamespace(identity=WORKER))

    @patch("vmbackups.jobs._target_pool", return_value=(MagicMock(), MagicMock()))
    def test_a_retention_deletion_checks_again_before_it_deletes(self, target_pool):
        oldest, *_rest = self.backups(*[Backup.READY] * 3)
        op, ctx = self.run_delete(oldest)
        BackupPolicy.objects.filter(pk=self.policy.pk).update(keep=5)  # raised meanwhile
        with self.assertRaisesMessage(OperationError, "no longer beyond"):
            DeleteBackup().run(op, ctx)
        self.assertTrue(Backup.objects.filter(pk=oldest.pk, state=Backup.READY).exists())
        op.refresh_from_db()
        self.assertFalse(op.effects_started)

    # -- target check ------------------------------------------------------

    def test_a_target_is_checked_once_a_day(self):
        BackupTarget.objects.filter(pk=self.target.pk).update(checked_at=at(2026, 11, 16, 9))
        schedule.check_targets(at(2026, 11, 17, 9))
        schedule.check_targets(at(2026, 11, 17, 9, 1))
        (op,) = Operation.objects.filter(kind="backup.check")
        self.assertEqual(op.params, {"target": self.target.pk})

    def test_a_failed_check_is_tried_again_an_hour_later(self):
        BackupTarget.objects.filter(pk=self.target.pk).update(checked_at=at(2026, 11, 16, 9))
        schedule.check_targets(at(2026, 11, 17, 9))
        (op,) = Operation.objects.filter(kind="backup.check")
        jobs.finish(op, jobs.Outcome(Operation.FAILED))
        schedule.check_targets(at(2026, 11, 17, 9, 1))
        self.assertEqual(Operation.objects.filter(kind="backup.check").count(), 1)
        Operation.objects.filter(pk=op.pk).update(finished_at=op.finished_at - datetime.timedelta(minutes=61))
        schedule.check_targets(at(2026, 11, 17, 10, 5))
        self.assertEqual(Operation.objects.filter(kind="backup.check").count(), 2)

    def run_check(self, names):
        op = jobs.submit("backup.check", self.admin, {"target": self.target.pk}, "key-check-0001")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        pool = MagicMock()
        pool.listVolumes.return_value = names
        with patch("vmbackups.jobs._target_pool", return_value=(MagicMock(), pool)):
            return CheckTarget().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def test_the_check_marks_missing_files_and_files_back(self):
        whole, gone = self.backups(Backup.READY, Backup.READY)
        for b in (whole, gone):
            BackupFile.objects.create(backup=b, role=BackupFile.DISK, dev="vda", volume=f"{b.prefix}-vda.qcow2")
        present = [f"{whole.prefix}-vda.qcow2", f"{whole.prefix}-manifest.json", f"{gone.prefix}-vda.qcow2"]
        result = self.run_check(present)  # gone's manifest is not there
        self.assertEqual(Backup.objects.get(pk=gone.pk).state, Backup.MISSING)
        self.assertEqual(Backup.objects.get(pk=whole.pk).state, Backup.READY)
        self.assertIn("vm1", result["warning"][0]["values"]["backups"])
        self.assertIsNotNone(BackupTarget.objects.get(pk=self.target.pk).checked_at)
        Operation.objects.all().delete()
        self.run_check([*present, f"{gone.prefix}-manifest.json"])
        self.assertEqual(Backup.objects.get(pk=gone.pk).state, Backup.READY)

    def test_a_backup_finished_minutes_ago_is_not_marked_missing(self):
        # written through another compute: this one's NFS client may not list its files yet
        (backup,) = self.backups(Backup.READY)
        Backup.objects.filter(pk=backup.pk).update(finished_at=timezone.now() - datetime.timedelta(minutes=2))
        self.run_check([])
        self.assertEqual(Backup.objects.get(pk=backup.pk).state, Backup.READY)
        Backup.objects.filter(pk=backup.pk).update(finished_at=timezone.now() - datetime.timedelta(minutes=20))
        self.run_check([])
        self.assertEqual(Backup.objects.get(pk=backup.pk).state, Backup.MISSING)

    def test_an_incremental_backup_whose_base_file_is_gone_is_missing(self):
        base, top = self.backups(Backup.READY, Backup.READY)
        Backup.objects.filter(pk=top.pk).update(parent=base)
        for b in (base, top):
            BackupFile.objects.create(backup=b, role=BackupFile.DISK, dev="vda", volume=f"{b.prefix}-vda.qcow2")
        self.run_check([f"{base.prefix}-manifest.json", f"{top.prefix}-vda.qcow2", f"{top.prefix}-manifest.json"])
        self.assertEqual(Backup.objects.get(pk=top.pk).state, Backup.MISSING)

    def test_a_check_that_reaches_no_pool_marks_nothing(self):
        (backup,) = self.backups(Backup.READY)
        op = jobs.submit("backup.check", self.admin, {"target": self.target.pk}, "key-check-0002")
        with patch("vmbackups.jobs._target_pool", side_effect=OperationError("No compute reaches %(t)s", t="nfs1")):
            with self.assertRaises(OperationError):
                CheckTarget().run(op, Context(op, SimpleNamespace(identity=WORKER)))
        self.assertEqual(Backup.objects.get(pk=backup.pk).state, Backup.READY)

    def test_the_pass_runs_from_the_worker(self):
        self.assertIn(schedule.run_schedules, jobs.PERIODIC)
