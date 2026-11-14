"""Chunks to an SSH compute reuse this process's SSH connection: each request
takes it for itself and opens its own SFTP session. A connection is not
reused after an error, when the host dropped it, when it is too old, or by
another login; an idle one is closed, and a forked worker leaves the
parent's connections to the parent."""

import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from storages import upload
from storages.upload import _ssh_pool, _UploadTarget
from vrtManager.connection import CONN_SSH


def client():
    return MagicMock(**{"get_transport.return_value.is_active.return_value": True})


KEY = ("192.0.2.1", 22, "root", "secret")


def target(host="192.0.2.1", login="root", passwd="secret"):
    return _UploadTarget(MagicMock(conn=CONN_SSH, host=host, login=login, passwd=passwd), "/pool", "x.iso", "id")


class SSHPoolTestCase(unittest.TestCase):
    def setUp(self):
        self.clients = []
        patcher = patch("paramiko.SSHClient", side_effect=lambda: self.clients.append(client()) or self.clients[-1])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(_ssh_pool.close_all)

    def request(self, **kwargs):
        with target(**kwargs) as t:
            return t.ssh

    def test_chunks_and_uploads_share_one_connection(self):
        first = self.request()
        self.assertIs(self.request(), first)
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(first.open_sftp.call_count, 2)
        first.close.assert_not_called()

    def test_another_login_port_or_password_has_its_own_connection(self):
        for kwargs in ({}, {"login": "admin"}, {"host": "192.0.2.1:2222"}, {"passwd": "changed"}):
            self.request(**kwargs)
        self.assertEqual(len(self.clients), 4)
        self.assertEqual(self.clients[2].connect.call_args.kwargs["port"], 2222)

    def test_two_requests_at_once_do_not_share_and_the_surplus_is_closed(self):
        with target() as a, target() as b:
            self.assertIsNot(a.ssh, b.ssh)
        first, second = self.clients  # b is given back first and kept
        first.close.assert_called_once()
        second.close.assert_not_called()
        self.assertIs(self.request(), second)

    def test_a_connection_is_not_reused_after_an_error(self):
        with self.assertRaises(OSError):
            with target():
                raise OSError("write failed")
        self.clients[0].close.assert_called_once()
        self.request()
        self.assertEqual(len(self.clients), 2)

    def test_a_dropped_connection_is_replaced(self):
        stale = self.request()
        stale.get_transport.return_value.is_active.return_value = False
        self.assertIsNot(self.request(), stale)
        stale.close.assert_called_once()

    def test_a_connection_whose_sftp_fails_is_replaced(self):
        stale = self.request()
        stale.open_sftp.side_effect = EOFError("connection reset")
        self.assertIsNot(self.request(), stale)
        stale.close.assert_called_once()

    def test_an_sftp_start_that_never_answers_is_ended(self):
        stale = self.request()
        closed = threading.Event()

        def hang():  # paramiko's wait for the subsystem, woken by a close
            closed.wait(5)
            raise EOFError("closed")

        stale.open_sftp.side_effect = hang
        stale.close.side_effect = closed.set
        start = time.monotonic()
        with patch("storages.upload.SSH_CONNECT_TIMEOUT_SECONDS", 0.05):
            self.assertIsNot(self.request(), stale)
        self.assertLess(time.monotonic() - start, 1)

    def test_a_connection_without_an_idle_timer_is_not_kept(self):
        idle = client()
        with patch("threading.Timer.start", side_effect=RuntimeError("can't start new thread")):
            _ssh_pool.give(KEY, idle, time.monotonic())
        idle.close.assert_called_once()
        self.assertEqual(_ssh_pool._idle, {})

    def test_a_connection_is_not_reused_after_its_lifetime(self):
        stale = self.request()
        with patch("storages.upload.time.monotonic", return_value=time.monotonic() + upload.SSH_MAX_AGE_SECONDS):
            self.assertIsNot(self.request(), stale)
        stale.close.assert_called_once()

    def test_an_idle_connection_is_closed(self):
        with patch("storages.upload.SSH_IDLE_SECONDS", 0.01):
            idle = self.request()
            time.sleep(0.2)
        idle.close.assert_called_once()
        self.assertIsNot(self.request(), idle)

    def test_an_old_timer_does_not_close_a_connection_given_back_since(self):
        first = self.request()
        old_timer = _ssh_pool._idle[KEY][2]
        self.request()  # taken and given back: a new timer
        _ssh_pool._expire(KEY, old_timer)
        first.close.assert_not_called()
        self.assertIs(self.request(), first)

    def test_a_forked_child_drops_the_parents_connections(self):
        parent = self.request()
        with _ssh_pool._lock:  # held while forking
            pid = os.fork()
        if pid == 0:
            ok = _ssh_pool._idle == {} and parent.get_transport.return_value.atfork.called
            with _ssh_pool._lock:
                pass
            os._exit(0 if ok and not parent.close.called else 1)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        parent.get_transport.return_value.atfork.assert_not_called()
        self.assertIs(self.request(), parent)


if __name__ == "__main__":
    unittest.main()
