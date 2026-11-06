"""Live checks of bounded connection opens against real libvirt.

Runs only with TEST_LIBVIRT_HOST set (a TCP compute, see vrtManager/tests/livetest.py);
TEST_LIBVIRT_SSH_HOST/_LOGIN add a reachable ssh compute. 192.0.2.1 is
TEST-NET-1: SYN packets to it are dropped, as for a host that went away
without a trace.

TEST_LIBVIRT_SSH_ALIASES=1 adds the ssh tests that need these entries in the
ssh configuration of the user running the tests (SSH_HOST is the ssh compute):

    Host wvc-alias
        HostName SSH_HOST
    Host wvc-relay
        HostName 127.0.0.1
        Port 2222
        HostKeyAlias SSH_HOST
    Host wvc-silent
        HostName 127.0.0.1
        Port 2223

TEST_LIBVIRT_SSH_JUMP=1 adds a ProxyJump test through
    Host wvc-jump
        HostName SSH_HOST
        ProxyJump user@another-host
"""

import os
import shutil
import socket
import subprocess
import threading
import time
import unittest

import libvirt
from vrtManager.connection import CONN_SSH, CONN_TCP, CONNECT_TIMEOUT, connection_manager
from vrtManager.tests import livetest

UNREACHABLE = "192.0.2.1"
KEEPALIVE_DEATH = 45  # keepalive (5, 5) closes a silent connection after ~30 s


def timed(*args):
    started = time.monotonic()
    try:
        return connection_manager.get_connection(*args), time.monotonic() - started
    except libvirt.libvirtError as err:
        return err, time.monotonic() - started


def ssh_processes(host):
    """ssh client processes (exact name) whose arguments mention host."""
    out = subprocess.run(["pgrep", "-a", "-x", "ssh"], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if host in line]


class Relay:
    """TCP relay that can hold all traffic (frozen) and pass it again (thawed);
    a frozen relay looks like a host that went silent."""

    def __init__(self, target, port=0, frozen=False):
        self.forwarding = threading.Event()
        if not frozen:
            self.forwarding.set()
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", port))
        self.server.listen(5)
        self.port = self.server.getsockname()[1]
        self.target = target
        self.closed = False
        self.sockets = []
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            upstream = socket.create_connection(self.target)
            self.sockets += [client, upstream]
            for a, b in ((client, upstream), (upstream, client)):
                threading.Thread(target=self.pump, args=(a, b), daemon=True).start()

    def pump(self, src, dst):
        try:
            while not self.closed:
                if not self.forwarding.wait(0.2):
                    continue
                src.settimeout(0.2)
                try:
                    data = src.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass

    def freeze(self):
        self.forwarding.clear()
        time.sleep(0.5)  # let a recv that was already waiting run out

    def thaw(self):
        self.forwarding.set()

    def close(self):
        """Stop, and end the relayed connections, as a host that went away would."""
        self.closed = True
        self.forwarding.set()
        try:
            self.server.shutdown(socket.SHUT_RDWR)  # wakes the accept; close alone does not
        except OSError:
            pass
        self.server.close()
        for sock in self.sockets:
            sock.close()


@unittest.skipUnless(livetest.enabled(), "Set TEST_LIBVIRT_HOST to run the live libvirt tests")
class LiveBoundedOpenTestCase(unittest.TestCase):
    def setUp(self):
        self.host = os.environ["TEST_LIBVIRT_HOST"]
        self.login = os.environ.get("TEST_LIBVIRT_LOGIN", "")
        self.password = os.environ.get("TEST_LIBVIRT_PASSWORD", "")
        self.ssh_host = os.environ.get("TEST_LIBVIRT_SSH_HOST")
        self.ssh_login = os.environ.get("TEST_LIBVIRT_SSH_LOGIN", "root")

    # Opening

    def test_unreachable_tcp_host_fails_within_the_timeout_then_at_once(self):
        args = (UNREACHABLE, "u", "p", CONN_TCP)
        first, took = timed(*args)
        self.assertIsInstance(first, libvirt.libvirtError)
        self.assertLess(took, CONNECT_TIMEOUT + 1)
        second, took = timed(*args)
        self.assertIsInstance(second, libvirt.libvirtError)
        self.assertLess(took, 0.5)

    @unittest.skipUnless(shutil.which("ssh"), "no ssh client")
    def test_unreachable_ssh_host_fails_within_the_timeout_and_leaves_no_ssh(self):
        result, took = timed(UNREACHABLE, "root", "", CONN_SSH)
        self.assertIsInstance(result, libvirt.libvirtError)
        self.assertLess(took, CONNECT_TIMEOUT + 1)
        time.sleep(12)  # the wrapper's ConnectTimeout is 10 s
        self.assertEqual(ssh_processes(UNREACHABLE), [], "an ssh process outlived its connect timeout")

    def test_a_daemon_that_never_answers_fails_within_the_timeout(self):
        silent = socket.socket()
        silent.bind(("127.0.0.1", 0))
        silent.listen(5)  # accepts (kernel backlog), never answers
        self.addCleanup(silent.close)
        result, took = timed(f"127.0.0.1:{silent.getsockname()[1]}", "u", "p", CONN_TCP)
        self.assertIsInstance(result, libvirt.libvirtError)
        self.assertLess(took, CONNECT_TIMEOUT + 1)

    def check_slow_open_completes_later(self, args, relay):
        first, _ = timed(*args)
        self.assertIsInstance(first, libvirt.libvirtError)
        relay.thaw()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            conn, _ = timed(*args)
            if not isinstance(conn, libvirt.libvirtError):
                break
            time.sleep(0.5)
        self.assertNotIsInstance(conn, libvirt.libvirtError)
        self.assertTrue(conn.getVersion())

    def test_a_slow_tcp_open_that_completes_later_is_used(self):
        relay = Relay((self.host, 16509), frozen=True)
        self.addCleanup(relay.close)
        self.check_slow_open_completes_later((f"127.0.0.1:{relay.port}", self.login, self.password, CONN_TCP), relay)

    # A connection whose host goes silent

    def check_silent_host_is_noticed_and_replaced(self, args, relay):
        old = connection_manager.get_connection(*args)
        relay.freeze()
        outcome = []

        def call():
            try:
                outcome.append(old.getVersion())
            except libvirt.libvirtError as err:
                outcome.append(err)

        caller = threading.Thread(target=call, daemon=True)
        caller.start()
        caller.join(KEEPALIVE_DEATH)  # keepalive must end the call by then
        if caller.is_alive():
            relay.close()  # cut the connection so the stuck call returns
            self.fail(f"a call on a silent connection still waits after {KEEPALIVE_DEATH} s")
        self.assertIsInstance(outcome[0], libvirt.libvirtError)
        relay.thaw()
        new, _ = timed(*args)
        self.assertNotIsInstance(new, libvirt.libvirtError)
        self.assertIsNot(new, old)
        self.assertTrue(new.getVersion())

    def test_a_silent_tcp_host_is_noticed_and_reconnected(self):
        relay = Relay((self.host, 16509))
        self.addCleanup(relay.close)
        self.check_silent_host_is_noticed_and_replaced((f"127.0.0.1:{relay.port}", self.login, self.password, CONN_TCP), relay)

    # ssh

    @unittest.skipUnless(os.environ.get("TEST_LIBVIRT_SSH_HOST"), "Set TEST_LIBVIRT_SSH_HOST (and _LOGIN) for an ssh compute")
    def test_a_reachable_ssh_host_connects_through_the_wrapper(self):
        conn, _ = timed(self.ssh_host, self.ssh_login, "", CONN_SSH)
        self.assertNotIsInstance(conn, libvirt.libvirtError)
        self.assertIn("command=", conn.getURI())
        self.assertTrue(conn.getVersion())

    @unittest.skipUnless(os.environ.get("TEST_LIBVIRT_SSH_ALIASES"), "Set TEST_LIBVIRT_SSH_ALIASES=1 (see the module docstring)")
    def test_an_ssh_config_alias_is_used(self):
        conn, _ = timed("wvc-alias", self.ssh_login, "", CONN_SSH)
        self.assertNotIsInstance(conn, libvirt.libvirtError)
        self.assertTrue(conn.getVersion())

    @unittest.skipUnless(os.environ.get("TEST_LIBVIRT_SSH_ALIASES"), "Set TEST_LIBVIRT_SSH_ALIASES=1 (see the module docstring)")
    def test_an_ssh_port_that_never_answers_fails_within_the_timeout(self):
        silent = socket.socket()
        silent.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        silent.bind(("127.0.0.1", 2223))
        silent.listen(5)  # no ssh banner ever comes
        self.addCleanup(silent.close)
        result, took = timed("wvc-silent", self.ssh_login, "", CONN_SSH)
        self.assertIsInstance(result, libvirt.libvirtError)
        self.assertLess(took, CONNECT_TIMEOUT + 1)

    @unittest.skipUnless(os.environ.get("TEST_LIBVIRT_SSH_ALIASES"), "Set TEST_LIBVIRT_SSH_ALIASES=1 (see the module docstring)")
    def test_a_slow_ssh_open_that_completes_later_is_used(self):
        relay = Relay((self.ssh_host, 22), port=2222, frozen=True)
        self.addCleanup(relay.close)
        self.check_slow_open_completes_later(("wvc-relay", self.ssh_login, "", CONN_SSH), relay)

    @unittest.skipUnless(os.environ.get("TEST_LIBVIRT_SSH_ALIASES"), "Set TEST_LIBVIRT_SSH_ALIASES=1 (see the module docstring)")
    def test_a_silent_ssh_host_is_noticed_and_reconnected(self):
        relay = Relay((self.ssh_host, 22), port=2222)
        self.addCleanup(relay.close)
        self.check_silent_host_is_noticed_and_replaced(("wvc-relay", self.ssh_login, "", CONN_SSH), relay)

    @unittest.skipUnless(os.environ.get("TEST_LIBVIRT_SSH_JUMP"), "Set TEST_LIBVIRT_SSH_JUMP=1 (see the module docstring)")
    def test_ssh_through_a_jump_host(self):
        conn, _ = timed("wvc-jump", self.ssh_login, "", CONN_SSH)
        self.assertNotIsInstance(conn, libvirt.libvirtError)
        self.assertTrue(conn.getVersion())
