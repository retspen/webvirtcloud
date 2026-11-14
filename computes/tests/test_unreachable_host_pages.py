"""A host page whose list could not be read says why, and not that the host has none."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from vrtManager.util import ConnectionFailed

from computes.models import Compute

EMPTY = {
    "storages": "This host has no storage pools.",
    "networks": "This host has no networks.",
    "interfaces": "libvirt lists no interfaces of this host.",
    "nwfilters": "This host has no network filters.",
    "virtsecrets": "This host has no secrets.",
}


class UnreachableHostPagesTestCase(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c", hostname="192.0.2.10", login="u", password="p", type=1)
        self.client.force_login(User.objects.create_superuser("hostadmin", "hostadmin@example.com", "pw"))

    def test_the_connection_error_shows_without_an_empty_list(self):
        failed = ConnectionFailed("Connection Failed: %(host)s did not answer within 5 s", host="192.0.2.10")
        for page, empty in EMPTY.items():
            with self.subTest(page), patch("vrtManager.connection.connection_manager.get_connection", side_effect=failed):
                content = self.client.get(reverse(page, args=[self.compute.id])).content.decode()
                self.assertIn("192.0.2.10 did not answer within 5 s", content)
                self.assertNotIn(empty, content)
