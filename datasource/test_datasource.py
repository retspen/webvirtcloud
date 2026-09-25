import json
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase
from django.urls import reverse

from computes.models import Compute
from datasource.views import get_client_ip, get_hostname_by_ip, os_index, os_metadata_json, os_userdata


class DataSourceTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client.login(username="admin", password="admin")
        self.compute = Compute.objects.create(
            name="test_compute",
            hostname="localhost",
            type=1,
        )

    def test_os_index(self):
        response = self.client.get(reverse("ds_openstack_index"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("latest", response.content.decode("utf-8"))

    def test_os_metadata_json_latest(self):
        response = self.client.get(reverse("ds_openstack_metadata", args=["latest"]))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["uuid"], "iid-dswebvirtcloud")
        self.assertIn("hostname", data)

    def test_os_metadata_json_invalid_version(self):
        response = self.client.get(reverse("ds_openstack_metadata", args=["v1"]))
        self.assertEqual(response.status_code, 404)

    def test_os_userdata_invalid_version(self):
        response = self.client.get(reverse("ds_openstack_userdata", args=["v1"]))
        self.assertEqual(response.status_code, 404)

    def test_get_client_ip_direct(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.10"
        self.assertEqual(get_client_ip(request), "192.168.1.10")

    def test_get_client_ip_forwarded(self):
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1, 192.168.1.50"
        self.assertEqual(get_client_ip(request), "192.168.1.50")

    def test_get_hostname_by_ip_fallback(self):
        # Invalid IP will cause gethostbyaddr to fail and return the IP string itself
        self.assertEqual(get_hostname_by_ip("256.256.256.256"), "256.256.256.256")

    def test_vdi_url_not_found_compute(self):
        response = self.client.get(reverse("vdi_url", args=[9999, "vm1"]))
        self.assertEqual(response.status_code, 404)
