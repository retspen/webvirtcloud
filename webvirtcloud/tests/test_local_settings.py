"""data/local_settings.py: an installation's own settings, run at the end of settings.py."""

import runpy
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class LocalSettingsTests(SimpleTestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base)
        (self.base / "webvirtcloud").mkdir()
        (self.base / "data").mkdir()
        shutil.copy(settings.BASE_DIR / "webvirtcloud" / "settings.py", self.base / "webvirtcloud" / "settings.py")

    def load(self):
        return runpy.run_path(str(self.base / "webvirtcloud" / "settings.py"))

    def test_it_sets_and_changes_the_defaults(self):
        (self.base / "data" / "local_settings.py").write_text(
            'TIME_ZONE = "Europe/Istanbul"\nALLOWED_HOSTS += ["panel.example.com"]\n')
        values = self.load()
        self.assertEqual(values["TIME_ZONE"], "Europe/Istanbul")
        self.assertIn("panel.example.com", values["ALLOWED_HOSTS"])
        self.assertIn("localhost", values["ALLOWED_HOSTS"])  # the defaults it added to stay

    def test_a_file_saved_with_a_byte_order_mark_is_read(self):
        (self.base / "data" / "local_settings.py").write_bytes(b'\xef\xbb\xbfTIME_ZONE = "Europe/Istanbul"\n')
        self.assertEqual(self.load()["TIME_ZONE"], "Europe/Istanbul")

    def test_without_it_the_defaults_hold(self):
        self.assertEqual(self.load()["WS_PORT"], 6080)

    def test_an_error_in_it_names_the_file(self):
        (self.base / "data" / "local_settings.py").write_text("ALLOWED_HOSTS = [\n")
        with self.assertRaises(SyntaxError) as error:
            self.load()
        self.assertEqual(error.exception.filename, str(self.base / "data" / "local_settings.py"))
