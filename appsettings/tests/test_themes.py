"""static/css/themes holds every theme in dev/scss/wvc-themes, compiled from
these sources with the pinned libsass (manage.py build_themes)."""

from django.test import SimpleTestCase

from appsettings.management.commands.build_themes import SCSS, compile_theme
from appsettings.views import THEMES_DIR


class ThemeTests(SimpleTestCase):
    def test_the_shipped_themes_are_compiled_from_these_sources(self):
        themes = sorted(p.name for p in (SCSS / "wvc-themes").iterdir() if p.is_dir())
        self.assertIn("zephyr", themes)
        self.assertEqual(sorted(p.name for p in THEMES_DIR.iterdir()), [f"{theme}.min.css" for theme in themes])
        for theme in themes:
            with self.subTest(theme=theme):
                self.assertEqual((THEMES_DIR / f"{theme}.min.css").read_text(), compile_theme(theme), "run manage.py build_themes")
