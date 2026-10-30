"""Console settings: each change is saved to the persistent definition, the
password only by the action chosen for it, and the VNC settings only while
the saved console type is VNC."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from instances.forms import ConsoleForm
from instances.models import Instance

VNC = {"console_type": "vnc", "listen_on": "127.0.0.1", "keymap": "auto", "password_action": "keep"}


class UpdateConsoleTestCase(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("console_admin", "c@example.com", "pw")
        self.client.force_login(admin)
        compute = Compute.objects.create(name="console-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(
            compute=compute, name="console-vm", uuid="11111111-2222-3333-4444-555555555555"
        )

    def post(self, data, console_type="vnc"):
        """console_type: the persistent definition's; the live one is VNC."""
        with patch("instances.models.wvmInstance") as wvm:
            proxy = wvm.return_value
            proxy.get_console_type.side_effect = lambda config=False: console_type if config else "vnc"
            proxy.get_console_listener_addr.return_value = "127.0.0.1"
            proxy.get_console_keymap.return_value = ""
            proxy.set_console_passwd.return_value = True
            response = self.client.post(reverse("instances:update_console", args=[self.instance.id]), data)
        return proxy, [str(m) for m in get_messages(response.wsgi_request)]

    def test_console_settings_are_applied(self):
        proxy, _ = self.post({**VNC, "listen_on": "0.0.0.0", "keymap": "de"})
        proxy.set_console_keymap.assert_called_once_with("de")
        proxy.set_console_listener_addr.assert_called_once_with("0.0.0.0")
        proxy.set_console_passwd.assert_not_called()

    def test_the_password_changes_by_the_action_chosen(self):
        for action, password in (("set", " a b c "), ("set", "éééé"), ("none", "")):
            with self.subTest(action, password=password):
                proxy, _ = self.post({**VNC, "password_action": action, "password": password})
                proxy.set_console_passwd.assert_called_once_with(password)
        proxy, _ = self.post({**VNC, "password_action": "generate"})
        (generated,), _ = proxy.set_console_passwd.call_args
        self.assertEqual(len(generated), 8)

    def test_a_password_vnc_cannot_take_is_refused_and_nothing_is_saved(self):
        for password in ("", "123456789", "ééééé"):  # libvirt counts bytes: é is two
            with self.subTest(password=password):
                proxy, messages = self.post({**VNC, "keymap": "de", "password_action": "set", "password": password})
                proxy.set_console_passwd.assert_not_called()
                proxy.set_console_keymap.assert_not_called()
                self.assertTrue(messages[0].startswith("Console settings were not saved"), messages)

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_a_new_serial_console_ignores_the_vnc_settings(self):
        # even ones that would be refused: an empty new password, an unknown keymap
        for vnc in ({"keymap": "de", "password_action": "none"},
                    {"keymap": "xx", "password_action": "set", "password": ""}):
            with self.subTest(vnc):
                proxy, messages = self.post({**VNC, **vnc, "console_type": "pty"})
                self.assertEqual(messages, [])
                proxy.set_console_type.assert_called_once_with("pty")
                proxy.set_console_keymap.assert_not_called()
                proxy.set_console_passwd.assert_not_called()

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    def test_a_saved_serial_console_shows_and_takes_no_vnc_settings(self):
        # the running VM still has VNC: the type to compare with is the saved one
        proxy, messages = self.post({"console_type": "pty"}, console_type="pty")
        self.assertEqual(messages, [])
        proxy.set_console_type.assert_not_called()
        proxy, _ = self.post({"console_type": "vnc", "keymap": "de"}, console_type="pty")
        proxy.set_console_type.assert_called_once_with("vnc")
        proxy.set_console_keymap.assert_not_called()
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_console_type.side_effect = lambda config=False: "pty" if config else "vnc"
            form = ConsoleForm(instance=Instance.objects.get(pk=self.instance.pk), is_superuser=True)
        self.assertEqual((form["console_type"].value(), sorted(form.fields)), ("pty", ["console_type"]))

    @override_settings(SERIAL_CONSOLE_ENABLED=False)
    def test_serial_is_not_offered_while_the_serial_console_is_off(self):
        proxy, _ = self.post({**VNC, "console_type": "pty"})
        proxy.set_console_type.assert_not_called()
