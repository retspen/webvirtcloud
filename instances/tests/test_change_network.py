from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance


class ChangeNetworkViewTestCase(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("net_admin", "n@example.com", "pw")
        self.client.force_login(admin)
        compute = Compute.objects.create(name="net-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(
            compute=compute, name="net-vm", uuid="11111111-2222-3333-4444-555555555555"
        )
        self.url = reverse("instances:change_network", args=[self.instance.id])

    def post(self, data):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 5
            self.client.post(self.url, data, HTTP_REFERER="/instances/%d/" % self.instance.id)
        return wvm.return_value.change_network

    def test_changes_the_nic_of_the_submitted_form(self):
        change = self.post({
            "net-old-mac-1": "52:54:00:00:00:02",
            "net-mac-1": "52:54:00:00:00:03",
            "net-source-1": "net:default",
            "net-nwfilter-1": "",
            "net-model-1": "e1000",
        })
        change.assert_called_once_with("52:54:00:00:00:02", "52:54:00:00:00:03", "default", "net", "e1000", "")

    def test_no_source_keeps_the_nics_own(self):
        change = self.post({"net-old-mac-1": "52:54:00:00:00:02", "net-source-1": "", "net-model-1": "e1000"})
        change.assert_called_once_with("52:54:00:00:00:02", "52:54:00:00:00:02", None, None, "e1000", "")

    def test_a_shut_off_vm_is_told_the_change_is_made(self):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 5
            response = self.client.post(self.url, {"net-old-mac-1": "52:54:00:00:00:02", "net-source-1": "net:default",
                                                   "net-model-1": "virtio"}, HTTP_REFERER="/instances/%d/" % self.instance.id)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], ["Network device changed"])

    def test_invalid_mac_is_rejected(self):
        change = self.post({
            "net-old-mac-0": "52:54:00:00:00:01",
            "net-mac-0": "52:54:00:00:00:01'/><evil/>",
            "net-source-0": "net:default",
        })
        change.assert_not_called()

    def test_missing_old_mac_is_rejected(self):
        change = self.post({"net-mac-0": "52:54:00:00:00:03", "net-source-0": "net:default"})
        change.assert_not_called()

    def test_missing_referer_redirects_to_the_instance(self):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 5
            response = self.client.post(self.url, {
                "net-old-mac-0": "52:54:00:00:00:01",
                "net-source-0": "net:default",
                "net-model-0": "virtio",
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/instances/{self.instance.id}/#network")
