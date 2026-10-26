"""The SSH console tunnel: ssh -W to the console's address or socket, never a
prompt, no remote shell, and its error output when it fails."""

import sys
import time
from unittest import TestCase
from unittest.mock import patch

from console import sshtunnels


class SshTunnelTests(TestCase):
    def test_ssh_forwards_to_the_console_without_a_shell_or_a_prompt(self):
        with patch.object(sshtunnels.subprocess, "Popen") as popen:
            sock, tunnel = sshtunnels.open_tunnel("kvm1.example.com", "root", "127.0.0.1:5900")
        sock.close()
        self.assertEqual(popen.call_args.args[0], [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-W", "127.0.0.1:5900",
            "-l", "root", "--", "kvm1.example.com"])
        self.assertIs(tunnel.process, popen.return_value)

    def test_the_target_on_the_compute(self):
        for address, unix_socket, target in (
            ("192.0.2.40", None, "192.0.2.40:5900"),
            ("2001:db8::40", None, "[2001:db8::40]:5900"),
            (None, None, "127.0.0.1:5900"),
            ("0.0.0.0", None, "127.0.0.1:5900"),
            ("::", None, "[::1]:5900"),
            ("localhost", None, "localhost:5900"),
            ("127.0.0.1", "/run/vnc.sock", "/run/vnc.sock"),
        ):
            with self.subTest(address=address, unix_socket=unix_socket):
                self.assertEqual(sshtunnels.tunnel_target(address, 5900, unix_socket), target)

    def fake_ssh(self, code):
        """A Tunnel whose process stands in for ssh."""
        return sshtunnels.Tunnel([sys.executable, "-c", code], None)

    def test_a_failed_tunnel_reports_what_ssh_said(self):
        failing = self.fake_ssh("import sys; sys.stderr.write('Host key verification failed.'); sys.exit(255)")
        failing.process.wait()  # ssh fails at once, before the session
        self.assertEqual(failing.close(), "Host key verification failed.")
        ended = self.fake_ssh("import time; time.sleep(30)")
        self.assertEqual(ended.close(), "")  # ended with the session: no error

    def test_much_error_output_does_not_stop_the_tunnel(self):
        # a pipe nobody reads stopped the writer at 64 KiB
        chatty = self.fake_ssh("import sys; sys.stderr.write('x' * 1_000_000); sys.exit(255)")
        chatty.process.wait(10)
        self.assertEqual(len(chatty.close()), 1_000_000)

    def test_an_ssh_that_ignores_terminate_is_killed(self):
        stubborn = self.fake_ssh("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)")
        time.sleep(1)  # the handler is set
        started = time.monotonic()
        stubborn.close()
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(stubborn.process.returncode, -9)
