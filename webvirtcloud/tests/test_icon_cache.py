"""Every {% bs_icon %} of the templates is in the committed icon cache
(webvirtcloud/bootstrap_icons.py): a missing one is an error page."""

import re
import unittest
from pathlib import Path

from django.conf import settings
from django.template import Context, Template

from webvirtcloud.bootstrap_icons import ICONS

BASE = Path(settings.BASE_DIR)
CALL = re.compile(r"\{%\s*bs_icon\s+(.*?)\s*%\}")
NAME = re.compile(r"""^['"]([^'"]+)['"]""")
KWARG = re.compile(r"""(\w+)=['"]([^'"]*)['"]""")


class IconCacheTestCase(unittest.TestCase):
    def test_every_template_icon_is_cached(self):
        cache = ICONS
        missing = []
        templates = [*BASE.glob("templates/**/*.html"), *BASE.glob("*/templates/**/*.html")]
        self.assertGreater(len(templates), 50)  # the globs still find the templates
        for template in templates:
            for args in CALL.findall(template.read_text(encoding="utf-8")):
                name = NAME.match(args)
                self.assertIsNotNone(name, f"{template}: icon name is not a literal: {args}")
                kw = dict(KWARG.findall(args))
                # the file name bs_icon reads
                cached = f"{name.group(1)}_{kw.get('size')}_{kw.get('color')}_{kw.get('extra_classes')}.svg".replace(" ", "_")
                if not (cache / cached).exists():
                    missing.append(f"{template.relative_to(BASE)}: {cached}")
        self.assertEqual(missing, [])

    def test_an_icon_is_its_svg_inline(self):
        html = Template("{% load bootstrap_icons %}{% bs_icon 'pencil' %}").render(Context())
        self.assertEqual(html, (ICONS / "pencil_None_None_None.svg").read_text(encoding="utf-8"))
        self.assertIn("<svg", html)
