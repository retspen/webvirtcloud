"""Loading the web app or novncd must not change how child processes are reaped.

With SIGCHLD ignored process-wide, the kernel reaps every child at once and
subprocess loses its exit status: a failing command reports 0.
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

CHECK = """
import signal, subprocess
assert signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL, signal.getsignal(signal.SIGCHLD)
print(subprocess.run(["false"]).returncode)
"""

LOAD_NOVNCD = """
import importlib.machinery, importlib.util
loader = importlib.machinery.SourceFileLoader("novncd", "console/novncd")
loader.exec_module(importlib.util.module_from_spec(importlib.util.spec_from_loader("novncd", loader)))
"""


class ChildProcessTestCase(unittest.TestCase):
    def run_python(self, code):
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip().splitlines()[-1]

    def test_failing_command_is_nonzero_after_loading_the_web_app(self):
        self.assertEqual(self.run_python("import webvirtcloud.wsgi\n" + CHECK), "1")

    def test_failing_command_is_nonzero_after_loading_novncd(self):
        self.assertEqual(self.run_python(LOAD_NOVNCD + CHECK), "1")
