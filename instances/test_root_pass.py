import json
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from instances.models import Instance


class SetRootPassTestCase(TestCase):
    def setUp(self):
        self.client.login(username="admin", password="admin")
        self.compute = Compute.objects.create(
            name="test_compute_root_pass",
            hostname="localhost",
            type=1,
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="root-pass-vm",
            uuid="87654321-4321-4321-4321-210987654321",
        )

    @patch("socket.socket")
    @patch.object(Instance, "proxy")
    def test_set_root_pass_post(self, mock_proxy, mock_socket_cls):
        mock_proxy.get_status.return_value = 5  # status: running
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = json.dumps({"return": "success"}).encode()

        response = self.client.post(
            reverse("instances:rootpasswd", args=[self.instance.id]),
            {"passwd": "newSecretPassword123"}
        )
        # Redirects back to referer or instance detail
        self.assertEqual(response.status_code, 302)

        # Check socket sent the command with hashed password
        self.assertTrue(mock_sock.send.called)
        sent_bytes = mock_sock.send.call_args[0][0]
        data = json.loads(sent_bytes.decode())
        self.assertEqual(data["action"], "password")
        self.assertEqual(data["vname"], "root-pass-vm")
        # SHA-512 crypt starts with $6$kgPoiREy$
        self.assertTrue(data["passwd"].startswith("$6$kgPoiREy$"))

    def test_set_root_pass_get_redirects(self):
        response = self.client.get(reverse("instances:rootpasswd", args=[self.instance.id]))
        self.assertEqual(response.status_code, 302)

    def test_set_root_pass_not_found(self):
        response = self.client.get(reverse("instances:rootpasswd", args=[99999]))
        self.assertEqual(response.status_code, 404)
