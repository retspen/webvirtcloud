"""The host pages' shared section links."""

from django.template.loader import render_to_string
from django.test import TestCase
from lxml import html

from computes.models import Compute


class HostNavTestCase(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c", hostname="192.0.2.1", login="u", password="p", type=1)

    def links(self, **context):
        nav = html.fromstring(render_to_string("computes/host_nav.html", {"compute": self.compute, **context}))
        return {link.text_content().strip(): (link.get("class"), link.get("aria-current")) for link in nav.iter("a")}

    def test_the_section_s_own_page_is_the_current_page(self):
        links = self.links(section="storages")
        self.assertEqual(len(links), 7)
        self.assertEqual(links["Storages"], ("nav-link active", "page"))
        self.assertEqual(links["Overview"], ("nav-link", None))

    def test_an_item_of_a_section_marks_the_section_without_being_its_page(self):
        self.assertEqual(self.links(section="networks", detail=True)["Networks"], ("nav-link active", "true"))
