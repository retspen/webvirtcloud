"""Real processes: a worker killed at each point is recovered by the next;
one worker per host; concurrent admissions and submissions never double up."""

import multiprocessing
import os
import shutil
import signal
import tempfile
import time

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TransactionTestCase, tag

from operations import claims, jobs
from operations.models import Claim, Operation, WorkerLease
from operations.tests import fakes, proc_kinds  # noqa: F401


def _worker(data):
    connections.close_all()
    from operations.worker import Worker
    os._exit(Worker(tick=0.05, heartbeat_every=0.2, grace=1, data=data).run())


def _admit(key, results):
    connections.close_all()
    try:
        claims.admit({key: Claim.EXCLUSIVE}, holder=f"p{os.getpid()}")
        results.put("admitted")
    except claims.Busy:
        results.put("busy")
    connections.close_all()
    results.close()
    results.join_thread()  # the feeder thread must deliver before os._exit
    os._exit(0)


def _submit(user_pk, results):
    connections.close_all()
    user = get_user_model().objects.get(pk=user_pk)
    try:
        results.put(str(jobs.submit("test.noop", user, {"uuid": "race"}, "key-race0001").pk))
    except Exception as err:
        results.put(f"error:{type(err).__name__}")
    connections.close_all()
    results.close()
    results.join_thread()
    os._exit(0)


@tag("processes")  # run outside the --parallel pool (webvirtcloud/test_runner.py)
class ProcessTestCase(TransactionTestCase):
    def setUp(self):
        self.ctx = multiprocessing.get_context("fork")
        self.user = get_user_model().objects.create_user("proc_user", "p@example.com", "pw")
        self.dir = tempfile.mkdtemp()
        self.children = []

    def tearDown(self):
        for p in self.children:
            if p.is_alive():
                p.kill()
            p.join(10)
        shutil.rmtree(self.dir, ignore_errors=True)

    def spawn(self, target, *args):
        connections.close_all()
        p = self.ctx.Process(target=target, args=args)
        p.start()
        self.children.append(p)
        return p

    def wait(self, predicate, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.1)
        return False

    def touch(self, name):
        open(os.path.join(self.dir, name), "w").close()

    def exists(self, name):
        return os.path.exists(os.path.join(self.dir, name))

    def test_concurrent_admissions_admit_once(self):
        results = self.ctx.Queue()
        for _ in range(8):
            self.spawn(_admit, "instance:race", results)
        outcomes = sorted(results.get(timeout=30) for _ in range(8))
        self.assertEqual(outcomes.count("admitted"), 1, outcomes)
        for p in self.children:
            p.join(10)
            self.assertEqual(p.exitcode, 0)

    def test_concurrent_duplicate_submissions_return_one_job(self):
        results = self.ctx.Queue()
        for _ in range(4):
            self.spawn(_submit, self.user.pk, results)
        outcomes = {results.get(timeout=30) for _ in range(4)}
        self.assertEqual(len(outcomes), 1, outcomes)
        self.assertFalse(any(o.startswith("error:") for o in outcomes), outcomes)
        self.assertEqual(Operation.objects.count(), 1)

    def test_a_second_worker_on_the_host_exits_with_1(self):
        first = self.spawn(_worker, self.dir)
        time.sleep(1)
        second = self.spawn(_worker, self.dir)
        second.join(15)
        self.assertEqual(second.exitcode, 1)
        os.kill(first.pid, signal.SIGTERM)
        first.join(15)
        self.assertEqual(first.exitcode, 0)

    def test_a_worker_of_another_installation_does_not_take_a_live_lease(self):
        first = self.spawn(_worker, self.dir)
        self.assertTrue(self.wait(lambda: WorkerLease.objects.exists()))
        holder = WorkerLease.objects.get().holder
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, True)
        second = self.spawn(_worker, other)  # its own flock: same hostname, another data directory
        time.sleep(2)
        self.assertEqual(WorkerLease.objects.get().holder, holder)
        for p in (first, second):
            os.kill(p.pid, signal.SIGTERM)
            p.join(15)
            self.assertEqual(p.exitcode, 0)

    def kill_at(self, point):
        op = jobs.submit("test.filesteps", self.user, {"dir": self.dir}, "key-proc0001")
        worker = self.spawn(_worker, self.dir)
        self.assertTrue(self.wait(lambda: self.exists("started")))
        if point == "after_effect":
            self.touch("go-intent")
            self.assertTrue(self.wait(lambda: self.exists("effect")))
        os.kill(worker.pid, signal.SIGKILL)
        worker.join(10)
        self.touch("go-intent")
        self.touch("go-finish")
        nxt = self.spawn(_worker, self.dir)
        try:
            self.assertTrue(self.wait(lambda: Operation.objects.get(pk=op.pk).state in Operation.TERMINAL))
        finally:
            os.kill(nxt.pid, signal.SIGTERM)
            nxt.join(15)
        return Operation.objects.get(pk=op.pk)

    def test_killed_before_intent_the_job_fails(self):
        op = self.kill_at("before_intent")
        self.assertEqual(op.state, Operation.FAILED)
        self.assertFalse(self.exists("effect"))

    def test_killed_after_the_effect_the_job_is_recovered_as_succeeded(self):
        op = self.kill_at("after_effect")
        self.assertEqual(op.state, Operation.SUCCEEDED)
        self.assertFalse(Claim.objects.filter(operation=op).exists())
