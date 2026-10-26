"""socketiod as a process: each client gets the output of its own console
worker, the worker is reaped, and a client without a valid token is refused.
The workers cannot reach libvirt here (the VMs' compute is the local socket),
so each ends with "Cannot open the console of <its VM>"."""

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from accounts.models import UserInstance
from computes.models import Compute
from console import tokens
from instances.models import Instance

try:
    import socketio
except ImportError:  # pragma: no cover
    socketio = None

ROOT = Path(__file__).resolve().parent.parent.parent
SOCKETIOD = ROOT / "console" / "socketiod"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def children(pid):
    """(pid, state) of the processes whose parent is pid."""
    found = []
    for entry in os.listdir("/proc"):
        try:
            with open("/proc/%s/stat" % entry) as f:
                fields = f.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if int(fields[1]) == pid:
            found.append((int(entry), fields[0]))
    return found


def consoles(pid):
    """(pid, state) of the console workers: children of socketiod's gunicorn worker."""
    return [c for worker, _ in children(pid) for c in children(worker)]


def start_socketiod(test):
    """socketiod on a free port, reading test's database; stopped at test's cleanup."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    db = {k: connection.settings_dict[k] for k in ("ENGINE", "USER", "PASSWORD", "HOST", "PORT", "OPTIONS")}
    db["NAME"] = str(connection.settings_dict["NAME"])
    (Path(tmp.name) / "socketiod_test_settings.py").write_text(
        "from webvirtcloud.settings import *  # noqa\n"
        "SERIAL_CONSOLE_ENABLED = True\n"
        "DATABASES = {'default': %r}\n" % db
    )
    port = free_port()
    env = dict(os.environ, DJANGO_SETTINGS_MODULE="socketiod_test_settings",
               PYTHONPATH=os.pathsep.join([tmp.name, str(ROOT)]))
    test.log = Path(tmp.name) / "socketiod.log"  # its stderr, as the journal would have it
    server = subprocess.Popen([sys.executable, str(SOCKETIOD), "-H", "127.0.0.1", "-p", str(port)],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=test.log.open("w"))
    test.addCleanup(lambda: (server.kill(), server.wait()))
    end = time.monotonic() + 20
    while time.monotonic() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return server, port
        test.assertIsNone(server.poll(), "socketiod exited at start")
        time.sleep(0.1)
    test.fail("socketiod did not listen within 20 s")


def console(port, token):
    """A connected client and what it receives until the server disconnects it."""
    client = socketio.Client(reconnection=False)
    received = {"output": [], "taken_over": [], "gone": threading.Event()}
    client.on("pty_output", lambda data: received["output"].append(data["output"]))
    client.on("taken_over", lambda data: received["taken_over"].append(data["by"]))
    client.on("disconnect", lambda *args: received["gone"].set())
    # the same origin as the server, as the page through nginx
    url = "http://127.0.0.1:%d" % port
    client.connect(url, auth={"token": token}, transports=["polling"], headers={"Origin": url})
    return client, received


@unittest.skipIf(socketio is None, "python-socketio is not installed")
@unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc")
class SocketiodProcessTestCase(TransactionTestCase):
    def setUp(self):
        compute = Compute.objects.create(name="local", hostname="localhost", login="", password="", type=4)
        user = get_user_model().objects.create_user("serial-owner", password="pw")
        self.tokens = {}
        for n, name in enumerate(("vm-a", "vm-b"), 1):
            vm = Instance.objects.create(compute=compute, name=name, uuid=f"22222222-0000-0000-0000-00000000000{n}")
            UserInstance.objects.create(user=user, instance=vm)
            self.tokens[name] = tokens.SIGNER.sign(f"{compute.id}:{vm.uuid}:{user.id}")
        self.server, self.port = start_socketiod(self)

    def console(self, token):
        return console(self.port, token)

    def test_each_client_gets_its_own_console(self):
        sessions = {name: self.console(token) for name, token in self.tokens.items()}
        for name, (client, received) in sessions.items():
            with self.subTest(name):
                received["gone"].wait(20)
                output = "".join(received["output"])
                self.assertIn("Cannot open the console of %s" % name, output)
                self.assertNotIn("vm-a" if name == "vm-b" else "vm-b", output)
                self.assertIn("console closed", output)
        end = time.monotonic() + 5
        while consoles(self.server.pid) and time.monotonic() < end:
            time.sleep(0.05)
        self.assertEqual(consoles(self.server.pid), [])
        self.assertIsNone(self.server.poll())
        # the operator finds why in socketiod's log, with the details the user is not shown
        log = self.log.read_text()
        for name in self.tokens:
            self.assertIn("serial console of VM %s did not open" % name, log)

    def test_a_client_without_a_valid_token_is_refused(self):
        for token in ("", "22-no-such-vm"):
            with self.subTest(token=token), self.assertRaises(socketio.exceptions.ConnectionError):
                self.console(token)
        self.assertEqual(consoles(self.server.pid), [])
