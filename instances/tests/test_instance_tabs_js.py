"""The VM page opens the tab a redirect points to (static/js/instance_tabs.js).
Its behaviour is checked with Node."""

import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)


class InstanceTabsTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_instance_tabs_js(self):
        result = subprocess.run(
            ["node", str(BASE / "instances/tests/js/instance_tabs.test.js"), str(BASE / "static/js/instance_tabs.js")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
