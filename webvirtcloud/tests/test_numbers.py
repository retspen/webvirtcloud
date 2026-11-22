"""Sizes and percentages on the pages: sizes in the binary units the forms ask
in, percentages as the page's language writes them."""

from django.test import SimpleTestCase
from django.utils import translation

from webvirtcloud.common_tags import binary_size, percent


class BinarySizeTests(SimpleTestCase):
    def test_a_size_takes_the_largest_unit_with_one_decimal_at_most(self):
        for size, shown in ((0, "0 B"), (None, "0 B"), (512, "512 B"), (1536, "1.5 KiB"), (512 * 2**20, "512 MiB"),
                            (int(3.8 * 2**30), "3.8 GiB"), (20 * 2**30, "20 GiB"), (1023.96 * 2**20, "1 GiB"),
                            (3 * 2**40, "3 TiB")):
            with self.subTest(size=size):
                self.assertEqual(binary_size(size), shown.replace(" ", "\xa0"))

    def test_the_decimal_mark_is_the_languages(self):
        with translation.override("tr"):
            self.assertEqual(binary_size(int(3.8 * 2**30)), "3,8\xa0GiB")


class PercentTests(SimpleTestCase):
    def test_each_language_puts_the_sign_where_it_writes_it(self):
        for language, shown in (("en", "13%"), ("tr", "%13"), ("zh-hans", "13%")):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(percent(13), shown)
        with translation.override("tr"):
            self.assertEqual(percent(12.5), "%12,5")
