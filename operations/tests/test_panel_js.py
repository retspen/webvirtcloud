import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)


class JobPanelJsTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_job_panel(self):
        result = subprocess.run(
            ["node", str(BASE / "operations/tests/js/job_panel.test.js"),
             str(BASE / "static/js/poll.js"), str(BASE / "operations/static/operations/job_panel.js")],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
