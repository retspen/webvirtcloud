"""The keyboard layout files the VNC console types text with."""

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from console.views import LAYOUTS_DIR

SCANCODES = Path(settings.BASE_DIR) / "static/js/novnc/core/input/xtscancodes.js"


def unique_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError(f"a key twice: {keys}")
    return dict(pairs)


class LayoutFilesTestCase(SimpleTestCase):
    def test_each_layout_file_is_a_layout(self):
        # the key codes noVNC sends as scancodes
        codes = {line.split('"')[1] for line in SCANCODES.read_text().splitlines() if line.startswith('  "')}
        paths = sorted(LAYOUTS_DIR.glob("*.json"))
        self.assertIn("us", [path.stem for path in paths])
        for path in paths:
            with self.subTest(path.name):
                layout = json.loads(path.read_text(), object_pairs_hook=unique_keys)
                self.assertRegex(path.stem, r"^[a-z]+(-[a-z0-9_]+)?$")
                self.assertEqual(set(layout), {"name", "source", "keys"})
                self.assertTrue(layout["name"])
                for code, characters in layout["keys"].items():
                    self.assertIn(code, codes)
                    self.assertEqual(len(characters), 4, code)
                    for character in characters:
                        # one printable character, or none
                        self.assertTrue(character is None or (len(character) == 1 and character.isprintable()),
                                        f"{code}: {character!r}")

    def test_us_and_turkish_q_type_every_printable_ascii_character(self):
        ascii_characters = {chr(c) for c in range(0x21, 0x7F)}
        for layout_id in ("us", "tr"):
            with self.subTest(layout_id):
                layout = json.loads((LAYOUTS_DIR / f"{layout_id}.json").read_text())
                typed = {c for characters in layout["keys"].values() for c in characters if c}
                self.assertEqual(ascii_characters - typed, set())
