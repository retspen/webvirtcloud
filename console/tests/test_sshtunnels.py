"""The SSH console tunnel: ssh -W to the console's address or socket, never a
prompt, no remote shell, and its error output when it fails."""

import sys
from unittest import TestCase
from unittest.mock import patch

from console import sshtunnels


class SshTunnelTests(TestCase):
    def test_ssh_forwards_to_the_console_without_a_shell_or_a_prompt(self):
        with patch.object(sshtunnels.subprocess, "Popen") as popen:
            sock, process = sshtunnels.open_tunnel("kvm1.example.com", "root", "127.0.0.1:5900")
        sock.close()
        self.assertEqual(popen.call_args.args[0], [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-W", "127.0.0.1:5900",
            "-l", "root", "--", "kvm1.example.com"])
        self.assertIs(process, popen.return_value)

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

    def test_a_failed_tunnel_reports_what_ssh_said(self):
        failing = sshtunnels.subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stderr.write('Host key verification failed.'); sys.exit(255)"],
            stderr=sshtunnels.subprocess.PIPE)
        failing.wait()  # ssh fails at once, before the session
        self.assertEqual(sshtunnels.close_tunnel(failing), "Host key verification failed.")
        ended = sshtunnels.subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                            stderr=sshtunnels.subprocess.PIPE)
        self.assertEqual(sshtunnels.close_tunnel(ended), "")  # ended with the session: no error
