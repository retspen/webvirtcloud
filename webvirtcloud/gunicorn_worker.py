"""gunicorn's threaded worker with the sync worker's request timeout."""

import os
import threading
import time

from gunicorn.workers.gthread import ThreadWorker


class Worker(ThreadWorker):
    """gunicorn kills a sync worker whose request runs past its timeout; a
    threaded worker keeps reporting in while one of its threads waits on a
    host that does not answer. This one exits when a request runs past the
    timeout, and gunicorn starts a new one: a request ends by then, as the
    short claims of operations.claims expect."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = {}  # thread: when its request started
        self.started_lock = threading.Lock()

    def handle(self, conn):
        thread = threading.get_ident()
        with self.started_lock:
            self.started[thread] = time.monotonic()
        try:
            return super().handle(conn)
        finally:
            with self.started_lock:
                del self.started[thread]

    def notify(self):
        with self.started_lock:
            oldest = min(self.started.values(), default=None)
        if oldest is not None and time.monotonic() - oldest > self.cfg.timeout:
            # a log write can block (a full pipe, a handler a stuck thread holds): it gets a second
            log = threading.Thread(target=self.log.critical, daemon=True,
                                   args=("A request ran past %s s: the worker exits", self.cfg.timeout))
            log.start()
            log.join(1)
            os._exit(1)  # its threads cannot be stopped, and exit() would wait for them
        super().notify()
