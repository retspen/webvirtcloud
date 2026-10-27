from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute

ERROR = "Connection Failed: Host key verification failed."


class OverviewStatusTests(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_superuser(username="ov-admin", password="pwd", email="ov@example.com")
        )
        # an ssh_config alias: not a name a TCP probe can reach
        self.compute = Compute.objects.create(name="ov-alias", hostname="wvc-alias", login="root", password="", type=2)

    def test_compute_list_shows_why_a_host_is_not_connected(self):
        with patch.object(Compute, "status", new_callable=PropertyMock, return_value=False), patch.object(
            Compute, "connection_error", new_callable=PropertyMock, return_value=ERROR
        ):
            response = self.client.get(reverse("computes"))
        self.assertContains(response, "Not connected")
        self.assertContains(response, ERROR)
