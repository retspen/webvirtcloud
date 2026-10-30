import contextlib
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

GSTFSD = Path(__file__).resolve().parent.parent.parent / "conf" / "daemon" / "gstfsd"
# the host's key (GSTFSD_KEY) and the panel's copy of it
KEY = "5e" * 32


def mac(kind, challenge, nonce, payload, key=KEY):
    message = "\n".join(("gstfsd-v1", kind, challenge, nonce, payload)).encode()
    return hmac.new(bytes.fromhex(key), message, hashlib.sha256).hexdigest()


def challenge_of(s):
    """The challenge gstfsd sends first, on one line."""
    line = b""
    while not line.endswith(b"\n"):
        chunk = s.recv(1)
        if not chunk:
            raise ConnectionError("gstfsd closed the connection")
        line += chunk
    return json.loads(line)["challenge"]


def signed(challenge, data, key=KEY, nonce="0f" * 32):
    """The request frame of the panel for this challenge."""
    request = json.dumps(data)
    return json.dumps({"nonce": nonce, "request": request, "mac": mac("request", challenge, nonce, request, key)}).encode()


def reply_of(s, challenge=None, nonce="0f" * 32):
    """gstfsd's reply; with the challenge, checked to be signed for it."""
    frame = json.loads(b"".join(iter(lambda: s.recv(4096), b"")))
    if challenge is not None:
        assert hmac.compare_digest(frame["mac"], mac("reply", challenge, nonce, frame["reply"])), frame
    return json.loads(frame["reply"])

# A stand-in for libguestfs: the guest's operating systems ("roots", each with
# its mountpoints), its files, and what is mounted live in a JSON file.
FAKE_GUESTFS = '''
import json, os
STATE = os.environ["FAKE_GUESTFS_STATE"]
def _load():
    with open(STATE) as f:
        return json.load(f)
def _save(state):
    with open(STATE, "w") as f:
        json.dump(state, f)
class GuestFS:
    def __init__(self, **kwargs):
        if _load().get("crash"):
            import sys
            sys.stderr.write("guestfs: the appliance crashed\\n")
            os._exit(3)
        self.launched = False
    def add_domain(self, name, **kwargs):
        if _load().get("fail_add"):
            raise RuntimeError("no domain named " + name)
    def launch(self):
        import time
        if _load().get("appliance"):
            # a stand-in for the appliance: a child process, like qemu
            import subprocess
            child = subprocess.Popen(["sleep", "60"])
            state = _load(); state["appliance_pid"] = child.pid; _save(state)
        time.sleep(_load().get("launch_seconds", 0))
        state = _load(); state["backend"] = os.environ.get("LIBGUESTFS_BACKEND"); _save(state)
        self.launched = True
    def inspect_os(self): return list(_load()["roots"])
    def inspect_get_mountpoints(self, root): return _load()["roots"][root]
    def mount(self, device, mountpoint):
        state = _load()
        if device in state.get("broken", []):
            raise RuntimeError("mount: wrong fs type on " + device)
        # a mountpoint needs its parent filesystem mounted first
        if mountpoint != "/" and "/" not in state["mounted"]:
            raise RuntimeError("mount: " + mountpoint + " does not exist")
        state["mounted"].append(mountpoint); state["history"].append([device, mountpoint]); _save(state)
    def umount_all(self):
        if not self.launched:
            raise RuntimeError("umount_all: call launch before using this function")
        state = _load(); state["mounted"] = []; _save(state)
    def shutdown(self):
        if not self.launched:
            raise RuntimeError("shutdown: call launch before using this function")
    def close(self):
        state = _load(); state["closed"] = True; _save(state)
    def _guest(self):
        if "/" not in _load()["mounted"]:
            raise RuntimeError("the guest root is not mounted")
    def is_file(self, path): self._guest(); return path in _load()["files"]
    def is_dir(self, path): self._guest(); return path in _load()["dirs"]
    def cat(self, path): self._guest(); return _load()["files"][path]
    def write(self, path, content):
        self._guest()
        import time
        time.sleep(_load().get("write_seconds", 0))
        state = _load()
        if state.get("fail_write"):
            raise RuntimeError("write: read-only file system")
        state["files"][path] = content; state["writes"] += 1; _save(state)
    def mkdir(self, path):
        self._guest(); state = _load(); state["dirs"].append(path); _save(state)
    def chmod(self, mode, path): self._guest()
    def feature_available(self, names): return not _load().get("no_selinuxrelabel")
    def selinux_relabel(self, specfile, path, force=None):
        self._guest(); state = _load()
        if specfile not in state["files"]:
            raise RuntimeError("selinux_relabel: " + specfile + ": No such file or directory")
        # with the number of writes before it: labels are set on written files
        state.setdefault("relabels", []).append([specfile, path, force, state["writes"]]); _save(state)
'''


def free_port(family=socket.AF_INET, host="127.0.0.1"):
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class GstfsdTestCase(unittest.TestCase):
    """gstfsd hardening."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Path(self.tmp.name, "guestfs.py").write_text(FAKE_GUESTFS)
        self.state = Path(self.tmp.name, "state.json")
        self.state.write_text(json.dumps({
            # one Linux guest with its root on LVM and a separate /boot
            "roots": {"/dev/vg/root": {"/": "/dev/vg/root", "/boot": "/dev/sda1"}},
            "files": {"/etc/shadow": "root:x:1::::::\n", "/root/.ssh/authorized_keys": "ssh-rsa OLD old@host\n"},
            "dirs": ["/root/.ssh"],
            "mounted": [],
            "history": [],
            "writes": 0,
        }))

    def _env(self, **extra):
        return dict(
            os.environ,
            PYTHONPATH=self.tmp.name,
            FAKE_GUESTFS_STATE=str(self.state),
            **{"GSTFSD_KEY": KEY, **extra},
        )

    def _start(self, host, port, family=socket.AF_INET, **env):
        proc = subprocess.Popen(
            [sys.executable, str(GSTFSD)],
            env=self._env(GSTFSD_BIND_HOST=host, GSTFSD_PORT=str(port), **env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        for _ in range(100):
            if proc.poll() is not None:
                self.fail("gstfsd exited: " + proc.stderr.read())
            try:
                with socket.socket(family, socket.SOCK_STREAM) as s:
                    s.connect((host, port))
                return proc
            except OSError:
                time.sleep(0.05)
        self.fail("gstfsd did not start listening")

    def _request(self, host, port, data, family=socket.AF_INET):
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((host, port))
            challenge = challenge_of(s)
            s.sendall(signed(challenge, data))
            # everything until gstfsd closes: more than one reply fails to parse
            return reply_of(s, challenge)

    def test_refuses_non_loopback_bind_without_opt_in(self):
        result = subprocess.run(
            [sys.executable, str(GSTFSD)],
            env=self._env(GSTFSD_BIND_HOST="0.0.0.0"),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GSTFSD_ALLOW_REMOTE", result.stderr)

    def test_public_key_is_appended_not_overwritten(self):
        port = free_port()
        self._start("127.0.0.1", port)
        reply = self._request(
            "127.0.0.1", port, {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 NEW new@host"}
        )
        self.assertEqual(reply["return"], "success")
        keys = json.loads(self.state.read_text())["files"]["/root/.ssh/authorized_keys"]
        self.assertEqual(keys.splitlines(), ["ssh-rsa OLD old@host", "ssh-ed25519 NEW new@host"])

    @unittest.skipUnless(socket.has_ipv6, "no IPv6")
    def test_refuses_a_deadline_the_panel_does_not_wait_for(self):
        # the panel gives up after 120 s and releases the VM
        proc = subprocess.run(
            [sys.executable, str(GSTFSD)],
            env=self._env(GSTFSD_PORT=str(free_port()), GSTFSD_DEADLINE="180"),
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("GSTFSD_DEADLINE", proc.stderr)

    def test_listens_on_ipv6_loopback(self):
        try:
            port = free_port(socket.AF_INET6, "::1")
        except OSError:
            self.skipTest("IPv6 loopback not available")
        self._start("::1", port, socket.AF_INET6)
        reply = self._request(
            "::1", port, {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 V6 v6@host"},
            socket.AF_INET6,
        )
        self.assertEqual(reply["return"], "success")

    def _update_state(self, **values):
        state = json.loads(self.state.read_text())
        state.update(values)
        self.state.write_text(json.dumps(state))

    def _serve(self):
        port = free_port()
        self._start("127.0.0.1", port)
        return port

    def test_only_a_request_signed_for_this_connection_is_done(self):
        port = self._serve()
        data = {"action": "password", "vname": "vm", "passwd": "$6$intruder"}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(("127.0.0.1", port))
            recorded = signed(challenge_of(s), data)  # a request of another connection, never sent there

        def tampered(challenge):
            frame = json.loads(signed(challenge, {"action": "password", "vname": "vm", "passwd": "$6$ok"}))
            frame["request"] = json.dumps(data)
            return json.dumps(frame).encode()

        for name, frame in (
            ("unsigned", lambda challenge: json.dumps(data).encode()),
            ("another key", lambda challenge: signed(challenge, data, key="a1" * 32)),
            ("changed after signing", tampered),
            ("recorded on another connection", lambda challenge: recorded),
            ("a nonce that is no nonce", lambda challenge: signed(challenge, data, nonce="x")),
        ):
            with self.subTest(name), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect(("127.0.0.1", port))
                s.sendall(frame(challenge_of(s)))
                reply = reply_of(s)
                self.assertEqual(reply, {"return": "error", "message": "the request is not signed with this host's gstfsd key"})
        state = json.loads(self.state.read_text())
        self.assertEqual((state["writes"], state["history"]), (0, []))  # no appliance was started

    def test_it_does_not_start_without_a_key(self):
        for key in ("", "5E" * 32, "5e" * 31):
            with self.subTest(key=key):
                result = subprocess.run([sys.executable, str(GSTFSD)], env=self._env(GSTFSD_KEY=key),
                                        capture_output=True, text=True, timeout=20)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("GSTFSD_KEY", result.stderr)

    def test_the_panel_asks_with_the_host_s_key(self):
        from unittest.mock import patch

        from instances import views
        from vrtManager.util import OperationError

        port = self._serve()
        compute = SimpleNamespace(name="host-a", hostname="127.0.0.1", gstfsd_key=KEY)
        with patch.object(views, "GSTFSD_PORT", port):
            self.assertEqual(views.gstfsd_request(compute, {"action": "password", "vname": "vm", "passwd": "$6$panel"}),
                             {"return": "success"})
            compute.gstfsd_key = "a1" * 32  # the key of another host
            with self.assertRaisesRegex(OperationError, "not signed with this host's gstfsd key"):
                views.gstfsd_request(compute, {"action": "password", "vname": "vm", "passwd": "$6$other"})
        self.assertIn("root:$6$panel:", json.loads(self.state.read_text())["files"]["/etc/shadow"])

    def test_root_password_is_set_on_the_guest_root(self):
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$new"})
        self.assertEqual(reply, {"return": "success"})
        state = json.loads(self.state.read_text())
        self.assertEqual(state["files"]["/etc/shadow"], "root:$6$new:1::::::\n")
        self.assertEqual(state["mounted"], [])
        self.assertTrue(state["closed"])

    def test_no_or_several_operating_systems_give_one_error(self):
        for roots in ({}, {"/dev/sda1": {"/": "/dev/sda1"}, "/dev/sdb1": {"/": "/dev/sdb1"}}):
            with self.subTest(roots=list(roots)):
                self._update_state(roots=roots)
                reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$x"})
                self.assertEqual(reply["return"], "error")
                self.assertEqual(json.loads(self.state.read_text())["files"]["/etc/shadow"], "root:x:1::::::\n")

    def test_a_failed_change_gives_one_error_and_cleans_up(self):
        self._update_state(fail_write=True)
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$x"})
        self.assertEqual(reply["return"], "error")
        self.assertIn("read-only", reply["message"])
        state = json.loads(self.state.read_text())
        self.assertEqual(state["mounted"], [])
        self.assertTrue(state["closed"])

    def test_a_long_key_arrives_whole(self):
        # longer than one read of the daemon (4096 bytes)
        key = "ssh-rsa " + "A" * 6000 + " long@host"
        reply = self._request("127.0.0.1", self._serve(), {"action": "publickey", "vname": "vm", "key": key})
        self.assertEqual(reply, {"return": "success"})
        keys = json.loads(self.state.read_text())["files"]["/root/.ssh/authorized_keys"]
        self.assertEqual(keys.splitlines()[-1], key)

    def test_the_root_is_mounted_before_the_filesystems_under_it(self):
        self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$x"})
        self.assertEqual(
            json.loads(self.state.read_text())["history"], [["/dev/vg/root", "/"], ["/dev/sda1", "/boot"]]
        )

    def test_a_broken_unrelated_filesystem_does_not_block_the_change(self):
        self._update_state(broken=["/dev/sda1"])  # /boot
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$y"})
        self.assertEqual(reply, {"return": "success"})
        self.assertEqual(json.loads(self.state.read_text())["files"]["/etc/shadow"], "root:$6$y:1::::::\n")

    def test_a_broken_filesystem_on_the_path_blocks_the_change(self):
        state = json.loads(self.state.read_text())
        state["roots"]["/dev/vg/root"]["/root"] = "/dev/vg/home"
        state["broken"] = ["/dev/vg/home"]
        self.state.write_text(json.dumps(state))
        reply = self._request("127.0.0.1", self._serve(), {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 K k@host"})
        self.assertEqual(reply["return"], "error")
        self.assertEqual(json.loads(self.state.read_text())["writes"], 0)

    def test_root_is_found_anywhere_in_shadow(self):
        self._update_state(files={"/etc/shadow": "daemon:*:1::::::\nroot:x:1::::::\n"})
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$z"})
        self.assertEqual(reply, {"return": "success"})
        self.assertEqual(
            json.loads(self.state.read_text())["files"]["/etc/shadow"], "daemon:*:1::::::\nroot:$6$z:1::::::\n"
        )

    def test_a_shadow_without_root_is_an_error(self):
        self._update_state(files={"/etc/shadow": "daemon:*:1::::::\n"})
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$z"})
        self.assertEqual(reply["return"], "error")
        self.assertEqual(json.loads(self.state.read_text())["writes"], 0)

    def test_an_early_failure_keeps_its_own_message(self):
        self._update_state(fail_add=True)
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$x"})
        self.assertEqual(reply["return"], "error")
        self.assertIn("no domain named vm", reply["message"])

    def test_a_request_in_two_pieces(self):
        port = self._serve()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(("127.0.0.1", port))
            challenge = challenge_of(s)
            body = signed(challenge, {"action": "password", "vname": "vm", "passwd": "$6$parts"})
            s.sendall(body[:10])
            time.sleep(0.3)
            s.sendall(body[10:])
            reply = reply_of(s, challenge)
        self.assertEqual(reply, {"return": "success"})

    def test_a_request_over_the_limit_is_refused(self):
        port = self._serve()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(("127.0.0.1", port))
            s.sendall(signed(challenge_of(s), {"action": "publickey", "vname": "vm", "key": "A" * 70000}))
            reply = reply_of(s)
        self.assertEqual(reply["return"], "error")
        self.assertEqual(json.loads(self.state.read_text())["writes"], 0)

    def test_a_trickling_client_is_cut_off(self):
        port = free_port()
        self._start("127.0.0.1", port, GSTFSD_DEADLINE="2")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("127.0.0.1", port))
            challenge_of(s)
            s.settimeout(0.25)
            start = time.monotonic()
            reply = b""
            # a space every quarter second: each read is quick, the request never completes
            while not reply and time.monotonic() - start < 8:
                try:
                    s.sendall(b" ")
                    reply = s.recv(4096)
                except socket.timeout:
                    pass
                except OSError:
                    break
        self.assertTrue(reply, "gstfsd kept reading a request that never completes")
        self.assertEqual(json.loads(json.loads(reply)["reply"])["return"], "error")

    def test_a_slow_write_is_stopped_at_the_deadline(self):
        # the whole change is bounded, not only its start: a write still
        # running at the deadline is killed with the appliance
        port = free_port()
        self._start("127.0.0.1", port, GSTFSD_DEADLINE="1")
        self._update_state(write_seconds=3)
        start = time.monotonic()
        reply = self._request("127.0.0.1", port, {"action": "password", "vname": "vm", "passwd": "$6$late"})
        self.assertLess(time.monotonic() - start, 2.5)
        self.assertEqual(reply["return"], "error")
        time.sleep(3)  # longer than the write would have taken
        self.assertEqual(json.loads(self.state.read_text())["writes"], 0)

    def test_a_key_needs_no_shadow_file(self):
        self._update_state(files={"/root/.ssh/authorized_keys": ""})
        reply = self._request("127.0.0.1", self._serve(), {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 K k@host"})
        self.assertEqual(reply, {"return": "success"})

    def _selinux_guest(self, selinuxtype="targeted", quote="", mode="enforcing"):
        state = json.loads(self.state.read_text())
        state["files"]["/etc/selinux/config"] = "SELINUX=%s\nSELINUXTYPE=%s%s%s\n" % (mode, quote, selinuxtype, quote)
        state["files"]["/etc/selinux/%s/contexts/files/file_contexts" % selinuxtype] = ""
        self.state.write_text(json.dumps(state))

    def test_a_key_gets_the_selinux_labels_of_the_guest(self):
        # a file libguestfs creates has no label, and sshd may not read an unlabeled authorized_keys
        port = self._serve()
        for i, quote in enumerate(("", '"', "'")):
            with self.subTest(quote=quote):
                self._selinux_guest("mls", quote)
                reply = self._request("127.0.0.1", port, {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 K%d k@host" % i})
                self.assertEqual(reply, {"return": "success"})
                state = json.loads(self.state.read_text())
                # once, after the key is written
                self.assertEqual(len(state.get("relabels", [])), i + 1)
                self.assertEqual(
                    state["relabels"][-1], ["/etc/selinux/mls/contexts/files/file_contexts", "/root/.ssh", True, state["writes"]]
                )

    def test_a_guest_without_selinux_is_not_relabeled(self):
        reply = self._request("127.0.0.1", self._serve(), {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 K k@host"})
        self.assertEqual(reply, {"return": "success"})
        self.assertNotIn("relabels", json.loads(self.state.read_text()))

    def test_a_guest_with_selinux_disabled_is_not_relabeled(self):
        # enabling SELinux again relabels the whole guest
        self._selinux_guest(mode="disabled")
        self._update_state(no_selinuxrelabel=True)
        reply = self._request("127.0.0.1", self._serve(), {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 K k@host"})
        self.assertEqual(reply, {"return": "success"})
        self.assertNotIn("relabels", json.loads(self.state.read_text()))

    def test_a_key_for_a_selinux_guest_needs_a_host_that_can_label(self):
        self._selinux_guest()
        self._update_state(no_selinuxrelabel=True)
        reply = self._request("127.0.0.1", self._serve(), {"action": "publickey", "vname": "vm", "key": "ssh-ed25519 K k@host"})
        self.assertEqual(reply["return"], "error")
        self.assertIn("SELinux", reply["message"])
        self.assertEqual(json.loads(self.state.read_text())["writes"], 0)

    def test_a_password_keeps_the_label_of_the_existing_shadow(self):
        # rewriting /etc/shadow keeps its file and label: no labelling needed
        self._selinux_guest()
        self._update_state(no_selinuxrelabel=True)
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$x"})
        self.assertEqual(reply, {"return": "success"})
        self.assertNotIn("relabels", json.loads(self.state.read_text()))

    def test_a_client_that_leaves_does_not_break_the_service(self):
        port = free_port()
        proc = self._start("127.0.0.1", port, GSTFSD_DEADLINE="1")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("127.0.0.1", port))
            challenge_of(s)
            s.sendall(b'{"nonce": ')
        time.sleep(1.5)  # gstfsd times the request out and answers a closed socket
        reply = self._request("127.0.0.1", port, {"action": "password", "vname": "vm", "passwd": "$6$after"})
        self.assertEqual(reply, {"return": "success"})
        proc.kill()
        self.assertNotIn("Traceback", proc.stderr.read())

    def test_nothing_is_written_after_the_deadline(self):
        # the panel gives up after its timeout; gstfsd must not write later
        port = free_port()
        self._start("127.0.0.1", port, GSTFSD_DEADLINE="1")
        self._update_state(launch_seconds=2)
        reply = self._request("127.0.0.1", port, {"action": "password", "vname": "vm", "passwd": "$6$late"})
        self.assertEqual(reply["return"], "error")
        state = json.loads(self.state.read_text())
        self.assertEqual(state["writes"], 0)
        self.assertEqual(state["mounted"], [])

    def test_the_appliance_runs_where_the_deadline_can_kill_it(self):
        # a libvirt-started appliance is no child of the worker: killing the
        # worker's process group would leave it writing to the disks
        port = free_port()
        self._start("127.0.0.1", port, LIBGUESTFS_BACKEND="libvirt")
        reply = self._request("127.0.0.1", port, {"action": "password", "vname": "vm", "passwd": "$6$d"})
        self.assertEqual(reply, {"return": "success"})
        self.assertEqual(json.loads(self.state.read_text())["backend"], "direct")

    def test_reading_the_request_counts_toward_the_deadline(self):
        # the panel waits a fixed time from connecting; a slow request leaves
        # less time for the change, not more
        port = free_port()
        self._start("127.0.0.1", port, GSTFSD_DEADLINE="2")
        self._update_state(launch_seconds=3)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(("127.0.0.1", port))
            start = time.monotonic()
            challenge = challenge_of(s)
            request = signed(challenge, {"action": "password", "vname": "vm", "passwd": "$6$slow"})
            s.sendall(request[:10])
            time.sleep(1.5)
            s.sendall(request[10:])
            reply = reply_of(s, challenge)
        self.assertEqual(reply["return"], "error")
        self.assertLess(time.monotonic() - start, 2.8)

    def test_a_crashed_worker_tells_why(self):
        self._update_state(crash=True)
        reply = self._request("127.0.0.1", self._serve(), {"action": "password", "vname": "vm", "passwd": "$6$c"})
        self.assertEqual(reply["return"], "error")
        self.assertIn("the appliance crashed", reply["message"])

    def test_a_client_that_leaves_stops_the_change(self):
        # the panel releases the VM when its connection breaks: nothing may
        # change the disks after that
        port = free_port()
        self._start("127.0.0.1", port)
        self._update_state(launch_seconds=2)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("127.0.0.1", port))
            s.sendall(signed(challenge_of(s), {"action": "password", "vname": "vm", "passwd": "$6$gone"}))
            time.sleep(0.5)
        time.sleep(3)  # longer than the change would have taken
        self.assertEqual(json.loads(self.state.read_text())["writes"], 0)

    def test_the_reply_waits_until_the_appliance_is_gone(self):
        port = free_port()
        self._start("127.0.0.1", port, GSTFSD_DEADLINE="1")
        self._update_state(appliance=True, launch_seconds=3)
        reply = self._request("127.0.0.1", port, {"action": "password", "vname": "vm", "passwd": "$6$late"})
        self.assertEqual(reply["return"], "error")
        pid = json.loads(self.state.read_text())["appliance_pid"]
        try:
            with open("/proc/%d/stat" % pid) as f:
                state = f.read().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            state = "gone"
        self.assertIn(state, ("gone", "Z"))


class GstfsdClientTestCase(unittest.TestCase):
    """The panel side checks that the reply is gstfsd's, signed for its request."""

    def ask(self, *sent):
        """gstfsd_request against a server that sends these, in pieces."""
        import threading
        from unittest.mock import patch

        from instances import views

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)

        def serve():
            conn, _ = server.accept()
            with conn, contextlib.suppress(OSError):  # the panel may hang up first
                conn.sendall(sent[0])
                conn.recv(65536)
                for piece in sent[1:]:
                    time.sleep(0.1)
                    conn.sendall(piece)

        thread = threading.Thread(target=serve)
        thread.start()
        self.addCleanup(thread.join, 5)
        compute = SimpleNamespace(name="host-a", hostname="127.0.0.1", gstfsd_key=KEY)
        with patch.object(views, "GSTFSD_PORT", server.getsockname()[1]):
            return views.gstfsd_request(compute, {"action": "publickey", "vname": "vm", "key": "k"})

    def test_a_reply_that_is_not_signed_is_refused(self):
        from vrtManager.util import OperationError

        challenge = json.dumps({"challenge": "1a" * 32}).encode() + b"\n"
        # something else on the port, which claims success in pieces, or sends what is no reply
        for name, sent in (
            ("unsigned success", (challenge, b'{"reply": "{\\"return\\": ', b'\\"success\\"}", "mac": ""}')),
            ("a mac that is no hex", (challenge, b'{"reply": "{}", "mac": "\xc3\xa9"}')),
            ("a mac that is no text", (challenge, b'{"reply": "{}", "mac": "\\ud800"}')),
            ("a challenge line without end", (b"{" + b" " * 70000,)),
            ("a reply too long", (challenge, b'{"reply": "' + b"x" * 70000 + b'"}')),
        ):
            with self.subTest(name), self.assertRaises(OperationError):
                self.ask(*sent)

    def test_a_host_without_a_key_is_not_asked(self):
        from unittest.mock import patch

        from instances import views
        from vrtManager.util import OperationError

        with patch("instances.views.socket.create_connection") as connect:
            with self.assertRaisesRegex(OperationError, "Set the gstfsd key of host-a first"):
                views.gstfsd_request(SimpleNamespace(name="host-a", hostname="127.0.0.1", gstfsd_key=""), {})
        connect.assert_not_called()
