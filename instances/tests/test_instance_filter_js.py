"""The instance list's search box and state list (static/js/instance_filter.js).
Its behaviour is checked with Node."""

import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)


class InstanceFilterTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_instance_filter_js(self):
        result = subprocess.run(
            ["node", str(BASE / "instances/tests/js/instance_filter.test.js"), str(BASE / "static/js/instance_filter.js")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
