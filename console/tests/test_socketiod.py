"""socketiod: who may connect, and each session's console kept to itself."""

import os
import select
import tempfile
import time
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.models import UserInstance
from computes.models import Compute
from console import tokens
from instances.models import Instance

SOCKETIOD = Path(__file__).resolve().parent.parent / "socketiod"


def load_socketiod():
    loader = SourceFileLoader("socketiod_under_test", str(SOCKETIOD))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class Base(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c", hostname="192.0.2.1", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm-a", uuid="11111111-0000-0000-0000-000000000001")
        self.user = get_user_model().objects.create_user("owner", password="pw")
        UserInstance.objects.create(user=self.user, instance=self.vm)

    def token(self, user=None, vm=None):
        vm = vm or self.vm
        return tokens.SIGNER.sign(f"{vm.compute_id}:{vm.uuid}:{(user or self.user).id}")


class TokenTestCase(Base):
    def test_a_token_opens_its_vm_for_a_user_who_may_open_it(self):
        self.assertEqual(tokens.authorize(self.token()), (self.vm, self.user))

    def test_refused_tokens(self):
        stranger = get_user_model().objects.create_user("stranger", password="pw")
        inactive = get_user_model().objects.create_user("inactive", password="pw", is_active=False)
        UserInstance.objects.create(user=inactive, instance=self.vm)
        cases = {
            "none": None,
            "legacy host-uuid": f"{self.compute.id}-{self.vm.uuid}",
            "tampered": self.token()[:-2] + "xx",
            "no access": self.token(stranger),
            "inactive user": self.token(inactive),
        }
        for name, token in cases.items():
            with self.subTest(name), self.assertRaises(PermissionError):
                tokens.authorize(token)
        token = self.token()
        with patch("django.core.signing.time.time", return_value=time.time() + tokens.MAX_AGE + 1):
            with self.assertRaises(PermissionError):
                tokens.authorize(token)


class SocketiodTestCase(Base):
    def setUp(self):
        super().setUp()
        self.d = load_socketiod()
        self.started = []
        self.killed_before_fork = []
        self.forks = iter(range(1000, 2000))
        patches = [
            patch.object(self.d.pty, "fork", side_effect=self.fork),
            patch.object(self.d.sio, "start_background_task", side_effect=lambda *a: self.started.append(a)),
            patch.object(self.d.os, "kill"),
            # the daemon closes its connection after each check; the test's transaction keeps it
            patch.object(self.d.db, "close_old_connections"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fork(self):
        self.killed_before_fork.append(self.d.os.kill.call_count)
        master, worker_side = os.openpty()
        self.addCleanup(lambda: [os.close(fd) for fd in (master, worker_side) if _open(fd)])
        return next(self.forks), master

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_a_valid_token_starts_a_console_for_its_session(self):
        self.assertIsNone(self.d.connect("sid-1", {}, {"token": self.token()}))
        self.assertEqual(self.d.sessions["sid-1"]["vm"], self.vm.pk)
        self.assertEqual(self.started[0][0], self.d.forward)

    def refused(self, sid, auth):
        with self.assertRaises(self.d.socketio.exceptions.ConnectionRefusedError) as refusal, \
                self.assertLogs("socketiod", level="INFO") as log:  # the reason is logged too
            self.d.connect(sid, {}, auth)
        self.assertIn(refusal.exception.error_args["message"], log.output[0])
        return refusal.exception.error_args["message"]

    def test_refused_connections_start_nothing_and_say_why(self):
        other = Instance.objects.create(compute=self.compute, name="vm-b", uuid="11111111-0000-0000-0000-000000000002")
        UserInstance.objects.create(user=self.user, instance=other)
        with override_settings(SERIAL_CONSOLE_ENABLED=False):
            self.assertIn("turned off", self.refused("off", {"token": self.token()}))
        with override_settings(SERIAL_CONSOLE_ENABLED=True):
            self.assertIn("expired", self.refused("no-auth", None))
            self.assertIn("expired", self.refused("bad", {"token": "x"}))
            self.assertIsNone(self.d.connect("first", {}, {"token": self.token()}))
            # one session per VM
            self.assertIn("another window", self.refused("second", {"token": self.token()}))
            with patch.object(self.d, "MAX_SESSIONS", 1):
                self.assertIn("Too many", self.refused("over", {"token": self.token(vm=other)}))
        self.assertEqual(list(self.d.sessions), ["first"])

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_input_and_resize_go_to_the_session_and_are_checked(self):
        self.d.connect("sid-1", {}, {"token": self.token()})
        fd = self.d.sessions["sid-1"]["fd"]
        with patch.object(self.d.os, "write", side_effect=lambda fd, data: len(data)) as write, \
                patch.object(self.d.fcntl, "ioctl") as ioctl:
            self.d.pty_input("sid-1", {"input": "ls\r"})
            for bad in (None, "ls", {"input": 7}):
                self.d.pty_input("sid-1", bad)
            self.d.pty_input("unknown", {"input": "x"})
            self.d.resize("sid-1", {"rows": 24, "cols": 80})
            for bad in ({"rows": 0, "cols": 80}, {"rows": 24, "cols": 501}, {"rows": "24", "cols": 80}, "x"):
                self.d.resize("sid-1", bad)
        self.assertEqual(write.call_count, 1)
        self.assertEqual((write.call_args.args[0], bytes(write.call_args.args[1])), (fd, b"ls\r"))
        self.assertEqual(ioctl.call_count, 1)

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_a_session_is_stopped_once(self):
        self.d.connect("sid-1", {}, {"token": self.token()})
        pid = self.d.sessions["sid-1"]["pid"]
        session = self.d.sessions["sid-1"]
        self.d.disconnect("sid-1")
        self.d.stop("sid-1")
        self.assertNotIn("sid-1", self.d.sessions)
        self.d.os.kill.assert_called_once_with(pid, self.d.signal.SIGKILL)
        # a closed session's fd number may belong to a new session: nothing uses it
        self.assertFalse(session["open"])
        with patch.object(self.d.os, "write") as write:
            self.d.pty_input("sid-1", {"input": "x"})
            session_input = self.d.sessions.get("sid-1")
        write.assert_not_called()
        self.assertIsNone(session_input)

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_a_superuser_takes_over_a_console_left_open(self):
        admin = get_user_model().objects.create_superuser("root", "root@example.com", "pw")
        self.d.connect("owner-tab", {}, {"token": self.token()})
        old = self.d.sessions["owner-tab"]
        killed_at_emit = []
        with patch.object(self.d.sio, "emit", side_effect=lambda *a, **k: killed_at_emit.append(self.d.os.kill.call_count)) as emit, \
                patch.object(self.d.sio, "disconnect") as disconnect:
            self.assertIsNone(self.d.connect("admin-tab", {}, {"token": self.token(admin)}))
        self.assertEqual(list(self.d.sessions), ["admin-tab"])
        self.assertFalse(old["open"])
        # the old worker was killed before the new one started: libvirt gives the console to one
        self.assertEqual(self.killed_before_fork, [0, 1])
        emit.assert_called_once_with("taken_over", {"by": "root"}, to="owner-tab")
        # told before its worker was killed: the old page's forward disconnects it then
        self.assertEqual(killed_at_emit, [0])
        disconnect.assert_called_once_with("owner-tab")

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_two_connections_at_once_start_one_console(self):
        import threading

        barrier, results = threading.Barrier(8), []

        def connect(n):
            barrier.wait()
            try:
                results.append(self.d.connect(f"sid-{n}", {}, {"token": self.token()}))
            except self.d.socketio.exceptions.ConnectionRefusedError:
                results.append("refused")

        threads = [threading.Thread(target=connect, args=(n,)) for n in range(8)]
        # the threads have their own database connections, outside this test's transaction
        with patch.object(self.d, "authorize", return_value=(self.vm, self.user)):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(sorted(results, key=str), [None] + ["refused"] * 7)
        self.assertEqual(len(self.d.sessions), 1)


class PasteTestCase(Base):
    """A real worker that echoes every byte twice: a paste far larger than the
    terminal's buffers goes through while its echo comes back. With the
    session lock held during a blocking write, the paste and its echo
    waited on each other for ever."""

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_a_large_paste_and_its_echo_do_not_wait_on_each_other(self):
        import threading

        d = load_socketiod()
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as script:
            # raw already: socketiod made the terminal raw before starting it
            script.write("import os\nwhile (data := os.read(0, 4096)):\n    os.write(1, data * 2)\n")
        self.addCleanup(os.unlink, script.name)
        echoed = []
        patches = [patch.object(d, "CONSOLECALLBACK", script.name), patch.object(d.db, "close_old_connections"),
                   patch.object(d.sio, "emit", side_effect=lambda event, data, to: echoed.append(len(data["output"]))),
                   patch.object(d.sio, "disconnect")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        d.connect("sid-1", {}, {"token": self.token()})
        self.addCleanup(d.stop, "sid-1")
        paste = threading.Thread(target=d.pty_input, args=("sid-1", {"input": "x" * 1_000_000}), daemon=True)
        paste.start()
        paste.join(30)
        self.assertFalse(paste.is_alive(), "the paste never finished")
        deadline = time.monotonic() + 30
        while sum(echoed) < 2_000_000 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(sum(echoed), 2_000_000)


class WorkerIsolationTestCase(Base):
    """A real fork: a session's worker holds no other session's console."""

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_a_worker_has_only_its_own_terminal(self):
        d = load_socketiod()
        other = Instance.objects.create(compute=self.compute, name="vm-b", uuid="11111111-0000-0000-0000-000000000002")
        UserInstance.objects.create(user=self.user, instance=other)
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as script:
            # stands in for consolecallback: prints the descriptors it holds
            script.write("import os, time\nprint(sorted(os.listdir('/proc/self/fd')))\ntime.sleep(5)\n")
        self.addCleanup(os.unlink, script.name)
        with patch.object(d, "CONSOLECALLBACK", script.name), patch.object(d.sio, "start_background_task"), \
                patch.object(d.db, "close_old_connections"):
            d.connect("first", {}, {"token": self.token()})
            d.connect("second", {}, {"token": self.token(vm=other)})
        self.addCleanup(lambda: [d.stop(sid) for sid in list(d.sessions)])
        output, fd = b"", d.sessions["second"]["fd"]
        while b"]" not in output:
            select.select([fd], [], [], 5)
            output += os.read(fd, 1024)
        # 0-2: its terminal, 3: socketiod's log, 4: the listing itself
        self.assertEqual(output.decode().strip(), "['0', '1', '2', '3', '4']")


def _open(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True
