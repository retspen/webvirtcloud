"""Each translated language of LANGUAGES gets its locale/ django.mo: Django
finds the catalog for the language code (zh-hans reads locale/zh) and every
message comes out as the catalog translates it, none covered by another
catalog."""

import gettext

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

CATALOG_DIRS = {"tr": "tr", "zh-hans": "zh", "uk": "uk"}


class CatalogTests(SimpleTestCase):
    def test_every_language_has_a_catalog(self):
        self.assertEqual({code for code, _ in settings.LANGUAGES} - {"en"}, set(CATALOG_DIRS))

    def test_every_message_is_translated_as_its_catalog_says(self):
        for code, directory in CATALOG_DIRS.items():
            path = settings.BASE_DIR / "locale" / directory / "LC_MESSAGES" / "django.mo"
            with open(path, "rb") as mo:
                catalog = gettext.GNUTranslations(mo)._catalog
            messages = {key: text for key, text in catalog.items() if isinstance(key, str) and key}
            self.assertGreater(len(messages), 100, path)
            with translation.override(code):
                for key, text in messages.items():
                    context, _, message = key.rpartition("\x04")
                    with self.subTest(language=code, message=message):
                        if context:
                            self.assertEqual(translation.pgettext(context, message), text)
                        else:
                            self.assertEqual(translation.gettext(message), text)
