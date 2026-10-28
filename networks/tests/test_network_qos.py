"""A network QoS the user typed wrong is refused with a message on the
network's page, not a server error."""

from unittest.mock import patch

import libvirt
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from networks.tests.driver import without_inactive_flag


class NetworkQosTests(TestCase):
    def test_a_rate_that_is_not_a_whole_number_is_refused(self):
        conn = libvirt.open("test:///default")
        self.addCleanup(conn.close)
        without_inactive_flag(self)
        compute = Compute.objects.create(name="qos-test", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("qos", "qos@example.com", "pw"))
        url = reverse("network", args=[compute.id, "default"])
        for rates in ({"qos_average": "abc"}, {"qos_average": "1", "qos_peak": "1.5"}):
            with self.subTest(rates=rates), \
                 patch("vrtManager.connection.connection_manager.get_connection", return_value=conn):
                response = self.client.post(url, {"set_qos": "", "qos_direction": "inbound", **rates})
                self.assertRedirects(response, url, fetch_redirect_response=False)
                self.assertIn("QoS rates must be whole numbers", [str(m) for m in get_messages(response.wsgi_request)])
