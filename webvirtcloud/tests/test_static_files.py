"""Source assets live in static/; collectstatic gathers them with the apps'
assets into STATIC_ROOT, outside the source tree."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

SOURCE = Path(settings.BASE_DIR) / "static"


class StaticFilesTestCase(SimpleTestCase):
    def test_static_root_is_not_the_source_dir(self):
        self.assertNotEqual(Path(settings.STATIC_ROOT).resolve(), SOURCE.resolve())
        self.assertIn(SOURCE, [Path(d) for d in settings.STATICFILES_DIRS])

    def test_no_collected_files_in_the_source_dir(self):
        for byproduct in ("staticfiles.json", "rest_framework"):
            self.assertFalse((SOURCE / byproduct).exists(), byproduct)
        self.assertEqual(list(SOURCE.rglob("*.gz")), [])

    def test_collectstatic_gathers_source_and_app_assets(self):
        with tempfile.TemporaryDirectory() as root, override_settings(STATIC_ROOT=root):
            call_command("collectstatic", "--noinput", verbosity=0)
            for name in ("css/webvirtcloud.css", "rest_framework/css/bootstrap.min.css"):
                self.assertTrue((Path(root) / name).exists(), name)
        self.assertIsNotNone(finders.find("css/webvirtcloud.css"))
