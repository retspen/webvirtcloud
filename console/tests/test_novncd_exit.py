"""novncd that cannot listen ends with a failure status, which systemd restarts."""

import socket
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent.parent


class NovncdExitTestCase(SimpleTestCase):
    def test_a_taken_port_ends_novncd_with_a_failure_status(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            novncd = subprocess.run([sys.executable, str(ROOT / "console" / "novncd"), "-v", "-H", "127.0.0.1",
                                     "-p", str(port)], cwd=ROOT, capture_output=True, timeout=60)
        self.assertNotEqual(novncd.returncode, 0)
        self.assertIn(b"Openening socket failed", novncd.stderr)
