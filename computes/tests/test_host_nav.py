"""The host pages' shared section links."""

from django.template.loader import render_to_string
from django.test import TestCase
from lxml import html

from computes.models import Compute


class HostNavTestCase(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c", hostname="192.0.2.1", login="u", password="p", type=1)

    def items(self, **context):
        nav = html.fromstring(render_to_string("computes/host_nav.html", {"compute": self.compute, **context}))
        return {item.text_content().strip(): (item.tag, item.get("aria-current")) for item in nav.xpath("//li/*")}

    def test_the_section_s_own_page_is_the_current_page(self):
        items = self.items(section="storages")
        self.assertEqual(len(items), 8)
        self.assertEqual(items["Storage"], ("span", "page"))
        self.assertEqual(items["Overview"], ("a", None))

    def test_an_item_of_a_section_links_the_section_as_where_it_is(self):
        self.assertEqual(self.items(section="networks", detail=True)["Networks"], ("a", "true"))
