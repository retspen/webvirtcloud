"""A confirmation says what its action does: every prompt in a template is the
button's own data-confirm text, shown by return confirm(this.dataset.confirm)."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ONCLICK = 'onclick="return confirm(this.dataset.confirm)"'


class ConfirmPromptTests(SimpleTestCase):
    def test_every_prompt_is_the_buttons_own_text(self):
        base = Path(settings.BASE_DIR)
        templates = [*base.glob("*/templates/**/*.html"), *base.glob("templates/**/*.html")]
        self.assertTrue(templates)
        for path in templates:
            text = path.read_text()
            at = text.find("confirm(")
            while at != -1:
                # the tag around it: prompt texts and template tags hold no < or >
                tag = text[text.rfind("<", 0, at):text.find(">", at) + 1]
                with self.subTest(template=str(path.relative_to(base)), tag=tag[:60]):
                    self.assertRegex(tag, r"^<(button|input|a)\b")
                    self.assertIn(ONCLICK, tag)
                    self.assertIn('data-confirm="', tag)
                    self.assertNotIn('data-confirm=""', tag)
                    self.assertNotIn("Are you sure", tag)
                at = text.find("confirm(", at + 1)
