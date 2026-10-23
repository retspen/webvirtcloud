"""A mutation view whose form field the UI always sends must not crash with a
500 when the field is missing (a malformed or direct request): it reports the
problem and returns to the VM page without changing anything."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from instances.models import Instance
from logs.models import Logs


class MissingFieldTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("mf", "mf@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row
        self.compute = Compute.objects.create(name="mf-c", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(
            compute=self.compute, name="mf-vm", uuid="11111111-2222-3333-4444-555555555555"
        )

    def post(self, name, data=None):
        with patch("instances.models.wvmInstance"), patch("instances.views.wvmInterface"):
            return self.client.post(
                reverse(f"instances:{name}", args=[self.instance.id]),
                data or {},
                HTTP_REFERER=f"http://testserver/instances/{self.instance.id}/",
            )

    def assert_reported(self, response):
        self.assertEqual(response.status_code, 302)
        levels = [m.level_tag for m in get_messages(response.wsgi_request)]
        self.assertIn("error", levels, "an error message is shown")
        self.assertFalse(Logs.objects.exists(), "nothing is logged as done")

    def test_add_network_without_a_network(self):
        self.assert_reported(self.post("add_network"))

    def test_add_network_mutation_is_not_attempted(self):
        with patch("instances.models.wvmInstance") as wvm, patch("instances.views.wvmInterface"):
            self.client.post(reverse("instances:add_network", args=[self.instance.id]), {})
            wvm.return_value.add_network.assert_not_called()

    def test_set_qos_without_a_mac(self):
        self.assert_reported(self.post("set_qos", {"qos_direction": "inbound"}))

    def test_set_qos_without_a_direction(self):
        self.assert_reported(self.post("set_qos", {"net-mac-0": "52:54:00:00:00:01"}))

    def test_resize_cpu_without_a_value(self):
        self.assert_reported(self.post("resizevm_cpu"))

    def test_resize_cpu_with_a_non_numeric_value(self):
        self.assert_reported(self.post("resizevm_cpu", {"vcpu": "lots", "cur_vcpu": "1"}))

    def test_resize_memory_without_a_value(self):
        self.assert_reported(self.post("resize_memory"))

    def test_resize_cpu_with_a_unicode_digit(self):
        # "²".isdigit() is True but int("²") raises; the guard must still hold
        self.assert_reported(self.post("resizevm_cpu", {"vcpu": "²", "cur_vcpu": "1"}))

    def test_resize_memory_with_a_unicode_digit(self):
        self.assert_reported(self.post("resize_memory", {"memory": "512", "cur_memory_custom": "²"}))

    def test_set_qos_with_non_numeric_rate(self):
        self.assert_reported(self.post("set_qos", {"qos_direction": "inbound", "net-mac-0": "52:54:00:00:00:01", "qos_average": "fast"}))

    def test_set_qos_with_an_invalid_direction(self):
        self.assert_reported(self.post("set_qos", {"qos_direction": "sideways", "net-mac-0": "52:54:00:00:00:01"}))

    def test_unset_qos_without_a_direction(self):
        self.assert_reported(self.post("unset_qos", {"net-mac": "52:54:00:00:00:01"}))

    def test_add_public_key_without_a_key(self):
        response = self.post("add_public_key")
        self.assertEqual(response.status_code, 302)
        levels = [m.level_tag for m in get_messages(response.wsgi_request)]
        self.assertIn("error", levels)

    def test_mutations_are_not_attempted(self):
        cases = {
            "set_qos": ({"qos_direction": "inbound"}, "set_qos"),
            "unset_qos": ({"net-mac": "52:54:00:00:00:01"}, "unset_qos"),
            "resizevm_cpu": ({}, "resize_cpu"),
            "resize_memory": ({}, "resize_mem"),
        }
        for view, (data, method) in cases.items():
            with self.subTest(view=view):
                with patch("instances.models.wvmInstance") as wvm, patch("instances.views.wvmInterface"):
                    self.client.post(reverse(f"instances:{view}", args=[self.instance.id]), data)
                    getattr(wvm.return_value, method).assert_not_called()
