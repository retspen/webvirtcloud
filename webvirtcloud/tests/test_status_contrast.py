"""Status colours keep their contrast on every theme: a status word is the
theme's pale status background with its dark status text, a pair that does
not depend on the page's background (dark themes keep light-mode emphasis
colours)."""

from unittest.mock import PropertyMock, patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from lxml import html


class StatusContrastTests(TestCase):
    def setUp(self):
        self.conn = libvirt.open("test:///default")
        self.addCleanup(self.conn.close)
        self.compute = Compute.objects.create(name="contrast", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("contrast", "c@example.com", "pw"))

    def page(self, name, *args, compute=True):
        with patch("vrtManager.connection.connection_manager.get_connection", return_value=self.conn):
            response = self.client.get(reverse(name, args=[self.compute.id, *args] if compute else args))
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def test_status_words_are_pale_badges_with_dark_text(self):
        # the test driver has no node memory statistics for the host row
        with patch.object(Compute, "ram_usage", new_callable=PropertyMock, return_value=1):
            status = self.page("instances:index", compute=False).xpath("//span[normalize-space()='Connected']")
        self.assertEqual(len(status), 1)
        for span in status:
            self.assertIn(span.get("class"), ("badge bg-success-subtle text-success-emphasis",
                                              "badge bg-danger-subtle text-danger-emphasis"))
