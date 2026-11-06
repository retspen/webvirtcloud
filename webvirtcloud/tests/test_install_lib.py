"""The installer's functions (conf/install-lib.sh), tested in bash."""

import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)


class InstallLibTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "bash is not installed")
    def test_install_lib(self):
        result = subprocess.run(
            ["bash", str(BASE / "webvirtcloud/tests/sh/install_lib.test.sh"), str(BASE / "conf/install-lib.sh")],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
