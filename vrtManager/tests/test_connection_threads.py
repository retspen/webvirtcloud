"""The worker uses the connection cache from many threads at once: one
cached connection per credentials, one reopen after a close, and never a
connection that the close callback cleared meanwhile."""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import libvirt
from vrtManager.connection import CONN_TCP, wvmConnectionManager


def alive_connection():
    conn = MagicMock()
    conn.isAlive.return_value = 1
    return conn


class ConnectionThreadsTestCase(unittest.TestCase):
    def setUp(self):
        patcher = patch("vrtManager.connection.wvmEventLoop")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = wvmConnectionManager()
        self.release = threading.Event()
        self.threads = set(threading.enumerate())
        self.addCleanup(self.finish_opens)
        self.opened = []

    def finish_opens(self):
        """Let every open this test started end: one ending later would run into another test."""
        self.release.set()
        for thread in set(threading.enumerate()) - self.threads:
            thread.join(5)

    def open_auth(self, *conns):
        pending = list(conns)

        def open_auth(uri, auth, flags):
            self.release.wait(5)
            conn = pending.pop(0)
            self.opened.append(conn)
            return conn

        return patch("vrtManager.connection.libvirt.openAuth", side_effect=open_auth)

    def get(self):
        try:
            return self.manager.get_connection("192.0.2.10", "u", "p", CONN_TCP)
        except libvirt.libvirtError as err:
            return err

    def get_from_threads(self, count=8):
        results = [None] * count

        def worker(i):
            results[i] = self.get()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        time.sleep(0.2)  # every thread is waiting for the open
        self.release.set()
        for t in threads:
            t.join(10)
        return results

    def entries(self):
        return self.manager._connections.get("192.0.2.10", [])

    def test_threads_share_one_cached_connection(self):
        conn = alive_connection()
        with self.open_auth(conn):
            results = self.get_from_threads()
        self.assertEqual(results, [conn] * 8)
        self.assertEqual(self.opened, [conn])
        self.assertEqual(len(self.entries()), 1)

    def test_after_a_close_threads_reopen_once(self):
        old, new = alive_connection(), alive_connection()
        with self.open_auth(old, new):
            self.release.set()
            self.assertIs(self.get(), old)
            self.release.clear()
            entry = self.entries()[0]
            entry._wvmConnection__connection_close_callback(old, 2)
            results = self.get_from_threads()
        self.assertEqual(results, [new] * 8)
        self.assertEqual(self.opened, [old, new])
        self.assertEqual(len(self.entries()), 1)

    def test_a_close_during_the_lookup_never_returns_none(self):
        """The close callback runs on the event loop thread, at any moment of
        another thread's get_connection: here while it checks the connection."""
        conn = alive_connection()
        self.release.set()
        with self.open_auth(conn):
            self.assertIs(self.get(), conn)
        entry = self.entries()[0]

        def is_alive():
            entry._wvmConnection__connection_close_callback(conn, 2)
            return 1

        conn.isAlive.side_effect = is_alive
        reopened = alive_connection()
        with self.open_auth(reopened):
            result = self.get()
        self.assertIsNone(entry.connection)  # the close came during the lookup
        self.assertIs(result, conn)  # the connection it checked, not None or an error


if __name__ == "__main__":
    unittest.main()
