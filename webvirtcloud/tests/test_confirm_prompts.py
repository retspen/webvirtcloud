"""A confirmation says what its action does, in the page's dialog: a button
asks its own data-confirm question through confirm_dialog.js, never the
browser's confirm()."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ConfirmPromptTests(SimpleTestCase):
    def test_every_prompt_is_a_buttons_own_text_in_the_pages_dialog(self):
        base = Path(settings.BASE_DIR)
        templates = [*base.glob("*/templates/**/*.html"), *base.glob("templates/**/*.html")]
        self.assertTrue(templates)
        for path in templates:
            text = path.read_text()
            with self.subTest(template=str(path.relative_to(base))):
                self.assertNotIn("confirm(", text)
            for match in re.finditer(r"data-confirm=", text):
                # the tag around it: prompt texts and template tags hold no < or >
                tag = text[text.rfind("<", 0, match.start()):text.find(">", match.start()) + 1]
                end = text.find("</button>", match.start())
                content = re.sub(r"\{%\s*(bs_icon|if|elif|else|endif)\b[^%]*%\}", "",
                                 text[text.find(">", match.start()) + 1:end]).strip()
                with self.subTest(template=str(path.relative_to(base)), tag=tag[:60]):
                    self.assertRegex(tag, r"^<button\b")
                    self.assertNotIn('data-confirm=""', tag)
                    self.assertNotIn("Are you sure", tag)
                    # the dialog's title and confirming button: the button's words, or an icon's name
                    self.assertTrue(content or "aria-label=" in tag or "title=" in tag)
