"""The threaded worker exits when a request runs past gunicorn's timeout."""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gunicorn.workers.gthread import ThreadWorker

from webvirtcloud.gunicorn_worker import Worker, request_progressed


def worker():
    w = Worker.__new__(Worker)
    w.cfg = SimpleNamespace(timeout=600)
    w.log = MagicMock()
    w.started, w.started_lock = {}, threading.Lock()
    return w


class WorkerTestCase(unittest.TestCase):
    def test_a_request_is_timed_while_it_runs(self):
        w = worker()
        seen = []
        with patch.object(ThreadWorker, "handle", lambda self, conn: seen.append(dict(self.started)) or "done"):
            self.assertEqual(w.handle("conn"), "done")
        self.assertEqual(list(seen[0]), [threading.get_ident()])
        self.assertEqual(w.started, {})

    def test_a_failed_request_is_no_longer_timed(self):
        w = worker()
        with patch.object(ThreadWorker, "handle", side_effect=OSError("reset")), self.assertRaises(OSError):
            w.handle("conn")
        self.assertEqual(w.started, {})

    def test_the_worker_reports_in_while_its_requests_are_within_the_timeout(self):
        w = worker()
        w.started[1] = time.monotonic() - 599
        with patch.object(ThreadWorker, "notify") as notify, patch("os._exit") as exit_:
            w.notify()
        notify.assert_called_once_with()
        exit_.assert_not_called()

    def test_a_request_that_still_sends_is_timed_from_its_last_progress(self):
        w = worker()
        w.started[threading.get_ident()] = time.monotonic() - 601
        with patch("webvirtcloud.gunicorn_worker._worker", w):
            request_progressed()
        with patch.object(ThreadWorker, "notify") as notify, patch("os._exit") as exit_:
            w.notify()
        notify.assert_called_once_with()
        exit_.assert_not_called()

    def test_the_worker_exits_when_a_request_runs_past_the_timeout(self):
        w = worker()
        w.started.update({1: time.monotonic(), 2: time.monotonic() - 601})
        with patch.object(ThreadWorker, "notify") as notify, patch("os._exit", side_effect=SystemExit) as exit_:
            with self.assertRaises(SystemExit):
                w.notify()
        exit_.assert_called_once_with(1)
        notify.assert_not_called()
        w.log.critical.assert_called_once()

    def test_a_log_that_blocks_does_not_keep_the_worker_from_exiting(self):
        w = worker()
        w.started[1] = time.monotonic() - 601
        w.log.critical.side_effect = lambda *args: threading.Event().wait(30)
        started = time.monotonic()
        with patch("os._exit", side_effect=SystemExit) as exit_, self.assertRaises(SystemExit):
            w.notify()
        exit_.assert_called_once_with(1)
        self.assertLess(time.monotonic() - started, 2)


if __name__ == "__main__":
    unittest.main()
