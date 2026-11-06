"""Only administrators choose where a VM's console listens. Other users who may
manage the console cannot make it listen beyond localhost, and cannot remove
the password of a console that does; such a refusal saves nothing."""

from unittest.mock import PropertyMock, patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from instances.models import Instance


class ConsoleListenerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("console-owner", password="pw")
        self.admin = User.objects.create_superuser("console-admin", password="pw", email="ca@example.com")
        compute = Compute.objects.create(name="cl", hostname="10.0.0.1", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="cl-vm", uuid="78787878-0000-0000-0000-000000000000")
        UserInstance.objects.create(user=self.owner, instance=self.vm, is_change=True, is_vnc=True)

    def post(self, user, data, local=True):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as wvm:
            proxy = wvm.return_value
            proxy.console_listens_locally.return_value = local
            proxy.get_console_listener_addr.return_value = "127.0.0.1" if local else "0.0.0.0"
            proxy.get_console_passwd.return_value = "Old-pass-1"
            proxy.get_console_keymap.return_value = ""
            proxy.set_console_passwd.return_value = True
            response = self.client.post(reverse("instances:update_console", args=[self.vm.id]), data)
        return proxy, [str(m) for m in get_messages(response.wsgi_request)]

    def test_owner_cannot_change_the_listen_address(self):
        proxy, _ = self.post(self.owner, {"listen_on": "0.0.0.0", "keymap": "auto", "password_action": "keep"})
        proxy.set_console_listener_addr.assert_not_called()

    def test_owner_cannot_remove_the_password_of_a_console_listening_beyond_localhost(self):
        proxy, messages = self.post(self.owner, {"password_action": "none", "keymap": "de"}, local=False)
        proxy.set_console_passwd.assert_not_called()
        proxy.set_console_keymap.assert_not_called()
        self.assertTrue(any("password" in m.lower() for m in messages), messages)

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_owner_can_switch_a_console_listening_beyond_localhost_to_serial(self):
        proxy, messages = self.post(self.owner, {"console_type": "pty", "password_action": "none", "keymap": "auto"},
                                    local=False)
        self.assertEqual(messages, [])
        proxy.set_console_type.assert_called_once_with("pty")
        proxy.set_console_passwd.assert_not_called()

    def test_owner_can_remove_the_password_of_a_local_console(self):
        proxy, _ = self.post(self.owner, {"password_action": "none", "keymap": "auto"})
        proxy.set_console_passwd.assert_called_once_with("")

    def test_owner_can_set_a_password_of_any_console(self):
        proxy, _ = self.post(self.owner, {"password_action": "set", "password": "s3cret-1", "keymap": "auto"}, local=False)
        proxy.set_console_passwd.assert_called_once_with("s3cret-1")

    def test_superuser_can_open_the_console_to_all_interfaces(self):
        proxy, _ = self.post(self.admin, {"listen_on": "0.0.0.0", "password_action": "none", "keymap": "auto"})
        proxy.set_console_listener_addr.assert_called_once_with("0.0.0.0")
        proxy.set_console_passwd.assert_called_once_with("")

    def test_owner_sees_the_listen_address_but_cannot_edit_it(self):
        self.client.force_login(self.owner)
        with patch("instances.models.wvmInstance") as wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ):
            proxy = wvm.return_value
            proxy.get_memory.return_value = 1024
            proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            proxy.get_console_listener_addr.return_value = "127.0.0.1"
            for name in ("get_networks", "get_ifaces", "get_storages", "get_disk_devices", "get_media_devices", "get_net_devices"):
                getattr(proxy, name).return_value = []
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_status.return_value = 5
            response = self.client.get(reverse("instances:instance", args=[self.vm.id]))
        form = response.context["console_form"]
        self.assertTrue(form.fields["listen_on"].disabled)
