"""A VM's console settings: who sees the form; each change is saved to the
persistent definition, the password only by the action chosen for it, and
the VNC settings only while the saved console type is VNC; only
administrators choose where a console listens beyond localhost."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from instances.forms import ConsoleForm, console_seen
from instances.models import Instance
from unittest.mock import PropertyMock
from accounts.models import UserInstance
from django.contrib.auth.models import Permission

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
            proxy.get_console_passwd.return_value = None
            proxy.set_console_passwd.return_value = True
            data = {"seen": console_seen(console_type, "127.0.0.1", "auto", None), **data}
            response = self.client.post(reverse("instances:update_console", args=[self.instance.id]), data)
        return proxy, [str(m) for m in get_messages(response.wsgi_request)]

    def test_console_settings_are_applied(self):
        proxy, _ = self.post({**VNC, "listen_on": "0.0.0.0", "keymap": "de"})
        proxy.set_console_keymap.assert_called_once_with("de")
        proxy.set_console_listener_addr.assert_called_once_with("0.0.0.0")
        proxy.set_console_passwd.assert_not_called()

    def test_a_page_opened_before_another_change_does_not_undo_it(self):
        # another administrator moved the console to localhost and set a keymap
        # or set a new password
        for stale in (console_seen("vnc", "0.0.0.0", "auto", None), console_seen("vnc", "127.0.0.1", "auto", "Other-1")):
            proxy, messages = self.post({**VNC, "listen_on": "0.0.0.0", "password_action": "generate", "seen": stale})
            proxy.set_console_listener_addr.assert_not_called()
            proxy.set_console_passwd.assert_not_called()
            self.assertEqual(messages[-1], "Console settings were not saved: "
                                           "The console settings were changed meanwhile; check them and save again.")

    def test_a_template_s_console_settings_are_not_changed(self):
        # its page has no console form: a template is cloned, not run
        self.instance.is_template = True
        self.instance.save()
        proxy, _ = self.post({**VNC, "keymap": "de"})
        proxy.set_console_keymap.assert_not_called()

    def test_the_password_changes_by_the_action_chosen(self):
        for action, password in (("set", " a b c "), ("set", "~a\\b{}!"), ("none", "")):
            with self.subTest(action, password=password):
                proxy, _ = self.post({**VNC, "password_action": action, "password": password})
                proxy.set_console_passwd.assert_called_once_with(password)
        proxy, _ = self.post({**VNC, "password_action": "generate"})
        (generated,), _ = proxy.set_console_passwd.call_args
        self.assertEqual(len(generated), 8)

    def test_a_password_vnc_cannot_take_is_refused_and_nothing_is_saved(self):
        # the browser console sends the password's characters, QEMU expects its bytes
        for password in ("", "123456789", "éé", "a\nb", "a\tb"):
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
        self.assertEqual((form["console_type"].value(), sorted(form.fields)), ("pty", ["console_type", "seen"]))

    def test_a_spice_console_stays_spice_when_its_settings_are_saved(self):
        # SPICE is not offered for new consoles: a save would have made it VNC
        proxy, messages = self.post({**VNC, "console_type": "spice", "keymap": "de"}, console_type="spice")
        self.assertEqual(messages, [])
        proxy.set_console_type.assert_not_called()
        proxy.set_console_keymap.assert_called_once_with("de")
        proxy, _ = self.post({**VNC, "console_type": "vnc"}, console_type="spice")
        proxy.set_console_type.assert_called_once_with("vnc")
        # the VNC limits are not SPICE's
        for password, saved in (("é-a-longer-one", True), ("a\nb", False)):
            with self.subTest(password=password):
                proxy, _ = self.post({**VNC, "console_type": "spice", "password_action": "set", "password": password},
                                     console_type="spice")
                self.assertEqual(proxy.set_console_passwd.called, saved)

    @override_settings(SERIAL_CONSOLE_ENABLED=False)
    def test_serial_is_not_offered_while_the_serial_console_is_off(self):
        proxy, _ = self.post({**VNC, "console_type": "pty"})
        proxy.set_console_type.assert_not_called()


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
            proxy.get_console_type.return_value = "vnc"
            data = {"seen": console_seen("vnc", "127.0.0.1" if local else "0.0.0.0", "auto", "Old-pass-1"), **data}
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


VNC_PASSWORD = "s3cretVNCpass"


class ConsoleSettingsAccessTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        view_perm = Permission.objects.get(codename="view_instances")
        self.superuser = User.objects.create_superuser(
            username="vncpw_super", email="vncpw_super@example.com", password="x"
        )
        self.staff_viewer = User.objects.create_user(
            username="vncpw_staff_viewer", password="x", is_staff=True
        )
        self.staff_viewer.user_permissions.add(view_perm)
        self.staff_owner = User.objects.create_user(
            username="vncpw_staff_owner", password="x", is_staff=True
        )
        self.vnc_owner = User.objects.create_user(username="vncpw_vnc_owner", password="x")

        self.compute = Compute.objects.create(
            name="vncpw-compute", hostname="127.0.0.1:1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="vncpw-vm",
            uuid="cccccccc-dddd-eeee-ffff-000000000000",
        )
        UserInstance.objects.create(
            instance=self.instance, user=self.staff_owner, is_change=True, is_vnc=False
        )
        UserInstance.objects.create(
            instance=self.instance, user=self.vnc_owner, is_change=True, is_vnc=True
        )

    def _detail_page(self, user):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as mock_wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ):
            proxy = mock_wvm.return_value
            proxy.get_memory.return_value = 1024
            proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            proxy.get_networks.return_value = []
            proxy.get_ifaces.return_value = []
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_storages.return_value = []
            proxy.get_console_passwd.return_value = VNC_PASSWORD
            proxy.get_console_type.return_value = "vnc"
            proxy.get_status.return_value = 5
            proxy.get_disk_devices.return_value = []
            proxy.get_media_devices.return_value = []
            proxy.get_net_devices.return_value = []
            response = self.client.get(
                reverse("instances:instance", args=[self.instance.id])
            )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_only_users_who_may_change_the_console_see_its_settings(self):
        form = reverse("instances:update_console", args=[self.instance.id])
        for user, shown in ((self.staff_viewer, False), (self.staff_owner, False),
                            (self.vnc_owner, True), (self.superuser, True)):
            with self.subTest(user.username):
                page = self._detail_page(user)
                self.assertEqual(form in page, shown)
                self.assertNotIn(VNC_PASSWORD, page)
