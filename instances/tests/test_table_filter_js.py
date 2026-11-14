"""The search box of the list pages, with the instance list's state list
(static/js/table_filter.js). Its behaviour is checked with Node."""

import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)


class TableFilterTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_table_filter_js(self):
        result = subprocess.run(
            ["node", str(BASE / "instances/tests/js/table_filter.test.js"), str(BASE / "static/js/table_filter.js")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
