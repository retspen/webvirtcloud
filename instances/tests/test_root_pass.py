import json
import socket
from unittest.mock import MagicMock, patch

from django.contrib.messages import get_messages
from django.test import RequestFactory, TestCase
from django.urls import reverse

from computes.models import Compute
from instances.models import Instance
from libvirt import libvirtError


class SetRootPassTestCase(TestCase):
    def setUp(self):
        self.client.login(request=RequestFactory().get("/"), username="admin", password="admin")
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
        # Renamed on the host: gstfsd must get the name of this UUID's domain
        mock_proxy.instance.name.return_value = "renamed-on-host"
        mock_proxy.get_status.return_value = 5  # shut off
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        replies = iter([json.dumps({"return": "success"}).encode(), b""] * 2)
        # one reply, then gstfsd closes the connection
        mock_sock.recv.side_effect = lambda size: next(replies)

        response = self.client.post(
            reverse("instances:rootpasswd", args=[self.instance.id]),
            {"passwd": "newSecretPassword123"}
        )
        # Redirects back to referer or instance detail
        self.assertEqual(response.status_code, 302)

        # Check socket sent the command with hashed password
        self.assertTrue(mock_sock.sendall.called)
        sent_bytes = mock_sock.sendall.call_args[0][0]
        data = json.loads(sent_bytes.decode())
        self.assertEqual(data["action"], "password")
        self.assertEqual(data["vname"], "renamed-on-host")
        # SHA-512 crypt with a random salt, not the old fixed one
        self.assertTrue(data["passwd"].startswith("$6$"))
        self.assertFalse(data["passwd"].startswith("$6$kgPoiREy$"))

    def test_set_root_pass_get_not_allowed(self):
        response = self.client.get(reverse("instances:rootpasswd", args=[self.instance.id]))
        self.assertEqual(response.status_code, 405)

    def test_set_root_pass_not_found(self):
        response = self.client.post(reverse("instances:rootpasswd", args=[99999]), {"passwd": "secret"})
        self.assertEqual(response.status_code, 404)

    @patch("socket.socket")
    @patch.object(Instance, "proxy")
    def test_same_password_gets_a_different_salt_each_time(self, mock_proxy, mock_socket_cls):
        mock_proxy.instance.name.return_value = "root-pass-vm"
        mock_proxy.get_status.return_value = 5
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        replies = iter([json.dumps({"return": "success"}).encode(), b""] * 2)
        # one reply, then gstfsd closes the connection
        mock_sock.recv.side_effect = lambda size: next(replies)
        url = reverse("instances:rootpasswd", args=[self.instance.id])

        self.client.post(url, {"passwd": "samePassword1"})
        self.client.post(url, {"passwd": "samePassword1"})

        hashes = [json.loads(c[0][0].decode())["passwd"] for c in mock_sock.sendall.call_args_list]
        self.assertEqual(len(hashes), 2)
        self.assertNotEqual(hashes[0], hashes[1])

    @patch("socket.socket")
    @patch.object(Instance, "proxy")
    def test_unreachable_gstfsd_is_an_error_message_not_a_crash(self, mock_proxy, mock_socket_cls):
        mock_proxy.instance.name.return_value = "root-pass-vm"
        mock_proxy.get_status.return_value = 5
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect.side_effect = socket.timeout("timed out")

        response = self.client.post(
            reverse("instances:rootpasswd", args=[self.instance.id]), {"passwd": "x"}
        )

        self.assertEqual(response.status_code, 302)
        mock_sock.settimeout.assert_called()

    @patch("socket.socket")
    @patch.object(Instance, "proxy")
    def test_add_public_key_unreachable_gstfsd_is_an_error_message(self, mock_proxy, mock_socket_cls):
        from accounts.models import UserSSHKey
        from django.contrib.auth import get_user_model

        admin = get_user_model().objects.get(username="admin")
        key = UserSSHKey.objects.create(user=admin, keyname="k", keypublic="ssh-ed25519 AAAA k")
        mock_proxy.instance.name.return_value = "root-pass-vm"
        mock_proxy.get_status.return_value = 5
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect.side_effect = ConnectionRefusedError()

        response = self.client.post(
            reverse("instances:add_public_key", args=[self.instance.id]), {"sshkeyid": key.id}
        )

        self.assertEqual(response.status_code, 302)
        mock_sock.settimeout.assert_called()


class GuestAgentAccessTestCase(TestCase):
    """A running VM whose guest agent answers gets its root password and SSH
    key through the agent; gstfsd serves only a shut-off VM."""

    def setUp(self):
        from accounts.models import UserSSHKey
        from django.contrib.auth import get_user_model

        self.client.login(request=RequestFactory().get("/"), username="admin", password="admin")
        compute = Compute.objects.create(name="agent-compute", hostname="192.0.2.1", type=1)
        self.instance = Instance.objects.create(compute=compute, name="agent-vm",
                                                uuid="11111111-2222-3333-4444-555555555555")
        admin = get_user_model().objects.get(username="admin")
        self.key = UserSSHKey.objects.create(user=admin, keyname="laptop", keypublic="ssh-ed25519 AAAA laptop")
        patcher = patch.object(Instance, "proxy")
        self.proxy = patcher.start()
        self.addCleanup(patcher.stop)
        self.proxy.get_status.return_value = 1  # running
        self.proxy.is_agent_ready.return_value = True

    def post(self, name, data):
        with patch("instances.views.gstfsd_request") as gstfsd:
            response = self.client.post(reverse(f"instances:{name}", args=[self.instance.id]), data)
        gstfsd.assert_not_called()
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_the_agent_sets_the_root_password(self):
        self.assertEqual(self.post("rootpasswd", {"passwd": "S3cret-pass"}), ["Reset root password"])
        user, crypted = self.proxy.set_user_password.call_args.args
        self.assertEqual(user, "root")
        self.assertTrue(crypted.startswith("$6$"))

    def test_the_agent_adds_the_ssh_key(self):
        self.assertEqual(self.post("add_public_key", {"sshkeyid": self.key.id}),
                         ["Installed new SSH public key laptop"])
        self.proxy.add_authorized_key.assert_called_once_with("root", "ssh-ed25519 AAAA laptop")

    def test_a_running_vm_without_its_agent_is_refused(self):
        self.proxy.is_agent_ready.return_value = False
        for name, data in (("rootpasswd", {"passwd": "S3cret-pass"}), ("add_public_key", {"sshkeyid": self.key.id})):
            # the latest message: the redirect is not followed, so earlier ones stay
            self.assertEqual(self.post(name, data)[-1], "Shut the VM down, or start its QEMU guest agent, and try again")
        self.proxy.set_user_password.assert_not_called()
        self.proxy.add_authorized_key.assert_not_called()

    def test_an_agent_that_refuses_is_an_error_message(self):
        self.proxy.set_user_password.side_effect = libvirtError("guest agent command failed: user root not found")
        self.assertEqual(self.post("rootpasswd", {"passwd": "S3cret-pass"}),
                         ["guest agent command failed: user root not found"])

    def test_a_user_who_does_not_see_hosts_gets_no_connection_details(self):
        from accounts.models import UserInstance
        from django.contrib.auth import get_user_model
        from libvirt import VIR_ERR_SYSTEM_ERROR, VIR_FROM_RPC

        owner = get_user_model().objects.create_user("agent-owner", password="pw")
        UserInstance.objects.create(user=owner, instance=self.instance, is_change=True)
        self.client.force_login(owner)
        err = libvirtError("Cannot recv data: 192.0.2.1:16509 Connection reset by peer")
        err.get_error_domain = lambda: VIR_FROM_RPC
        err.get_error_code = lambda: VIR_ERR_SYSTEM_ERROR
        self.proxy.set_user_password.side_effect = err
        self.assertEqual(self.post("rootpasswd", {"passwd": "S3cret-pass"}),
                         ["The host of this virtual machine cannot be reached right now."])
