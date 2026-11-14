"""Every response carries the Content-Security-Policy, and no template has
what its script-src 'self' would block: an inline script, an inline event
handler or a javascript: URL."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

# a <script> without src that is not json_script data
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>")
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=", re.I)


class ContentSecurityPolicyTests(TestCase):
    def test_pages_and_redirects_carry_the_policy(self):
        for url in (reverse("accounts:login"), reverse("index")):  # a page, and a redirect to the login
            with self.subTest(url=url):
                policy = self.client.get(url)["Content-Security-Policy"]
                self.assertEqual(
                    policy,
                    "script-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
                )


class TemplatesRunNoInlineScriptTests(SimpleTestCase):
    def test_no_template_has_an_inline_script_handler_or_javascript_url(self):
        base = Path(settings.BASE_DIR)
        templates = [*base.glob("*/templates/**/*.html"), *base.glob("templates/**/*.html")]
        self.assertTrue(templates)
        for path in templates:
            source = path.read_text()
            with self.subTest(template=str(path.relative_to(base))):
                self.assertIsNone(INLINE_SCRIPT.search(source))
                self.assertIsNone(INLINE_HANDLER.search(source))
                self.assertNotIn("javascript:", source)
