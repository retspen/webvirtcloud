"""Host interface changes write rows on the Logs page."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from logs.models import Logs


class InterfaceRowTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="c1", hostname="localhost", login="", password="", type=4)
        self.client.force_login(get_user_model().objects.create_superuser("audit-admin", "a@example.com", "pw"))
        Logs.objects.all().delete()  # the login's row

    @patch("interfaces.views.wvmInterface")
    @patch("interfaces.views.wvmInterfaces")
    def test_interface_actions(self, ifaces, iface):
        ifaces.return_value.can_change_interfaces.return_value = True
        ifaces.return_value.get_net_devices.return_value = ["eth0"]
        ifaces.return_value.get_member_candidates.return_value = ["eth0"]
        ifaces.return_value.get_ifaces_info.return_value = []
        iface.return_value.can_change_interfaces.return_value = True
        self.client.post(reverse("interfaces", args=[self.compute.id]), {
            "create": "", "name": "br1", "itype": "bridge", "start_mode": "onboot", "netdev": "eth0",
            "ipv4_type": "dhcp", "ipv6_type": "none", "stp": "on", "delay": "0"})
        ifaces.return_value.create_iface.assert_called_once()
        url = reverse("interface", args=[self.compute.id, "br1"])
        for action in ("start", "stop", "delete"):
            self.client.post(url, {action: ""})
        self.assertEqual(list(Logs.objects.order_by("id").values_list("message", "success", "host")), [
            ("Interface br1: add", True, "c1"),
            ("Interface br1: start", True, "c1"),
            ("Interface br1: stop", True, "c1"),
            ("Interface br1: delete", True, "c1"),
        ])
