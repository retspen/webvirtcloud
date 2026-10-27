# pylint: disable=no-member
import importlib.machinery
import json
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

from accounts.models import UserInstance
from appsettings.models import AppSettings
from computes.models import Compute
from console.views import LAYOUTS_DIR
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.signing import TimestampSigner
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from instances.models import Instance
from libvirt import libvirtError
from lxml import html

# Dynamically load console/novncd script for testing
NOVNCD_PATH = str(Path(__file__).resolve().parent.parent / "novncd")
_loader = importlib.machinery.SourceFileLoader("novncd_mod", NOVNCD_PATH)
_spec = importlib.util.spec_from_file_location(
    "novncd_mod", NOVNCD_PATH, loader=_loader
)
assert _spec is not None
assert _spec.loader is not None
novncd_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(novncd_mod)


def vnc_config(response):
    """What the VNC page's script starts from."""
    return json.loads(html.fromstring(response.content).get_element_by_id("vnc-config").text)


class ConsoleViewsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_user = (
            User.objects.filter(is_superuser=True).first()
            or User.objects.filter(username="admin").first()
            or User.objects.create_superuser(
                username="admin_console_test",
                email="admin@example.com",
                password="adminpassword",
            )
        )
        cls.alice = User.objects.create_user(
            username="alice", email="alice@example.com", password="alicepassword"
        )
        cls.bob = User.objects.create_user(
            username="bob", email="bob@example.com", password="bobpassword"
        )

        # SSH: novncd reaches any console listener (a TCP host's loopback one it cannot)
        cls.compute = Compute.objects.create(
            name="test-compute",
            hostname="127.0.0.1",
            login="root",
            password="",
            type=2,
        )

        cls.instance = Instance.objects.create(
            compute=cls.compute,
            name="vm-alpha",
            uuid="11111111-2222-3333-4444-555555555555",
        )

        # Grant alice ownership of vm-alpha
        UserInstance.objects.create(
            user=cls.alice,
            instance=cls.instance,
        )

        cls.url = reverse("console", args=[cls.compute.id, cls.instance.uuid])

    @patch("console.views.wvmInstance")
    def test_console_superuser_vnc(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_passwd.return_value = None
        mock_conn.get_console_passwd.return_value = "vncsecret"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc.html")
        config = vnc_config(response)
        signer = TimestampSigner(salt="console.novnc")
        unsigned = signer.unsign(config["token"], max_age=120)
        self.assertEqual(
            unsigned, f"{self.compute.id}:{self.instance.uuid}:{self.admin_user.id}"
        )
        self.assertEqual(config["password"], "vncsecret")

    @patch("console.views.wvmInstance")
    def test_console_unsupported_graphics_type(self, mock_wvm):
        # Only VNC is supported; a VM defined elsewhere may use another type.
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "rdp"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-error.html")
        self.assertIn("'rdp' is not supported", str(response.context["console_error"]))

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    @patch("console.views.wvmInstance")
    def test_console_superuser_pty(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "pty"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = self.url
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-xterm.html")
        # the page's credential for socketiod, as data
        signed = json.loads(html.fromstring(response.content).get_element_by_id("serial-token").text)
        self.assertEqual(TimestampSigner(salt="console.novnc").unsign(signed),
                         f"{self.compute.id}:{self.instance.uuid}:{self.admin_user.id}")

    @override_settings(SERIAL_CONSOLE_ENABLED=False)
    @patch("console.views.wvmInstance")
    def test_console_pty_refused_when_serial_console_disabled(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "pty"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = self.url
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateNotUsed(response, "console-xterm.html")
        self.assertIn("Serial console is disabled", str(response.context["console_error"]))
        # an element of the page, not a script's string
        alert = html.fromstring(response.content).xpath("//div[@role='alert']")
        self.assertIn("Serial console is disabled on this server", alert[0].text_content())

    @patch("console.views.wvmInstance")
    def test_console_user_assigned_instance_access(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_passwd.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.alice)
        url = self.url
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc.html")

    @patch("console.views.wvmInstance")
    def test_the_console_password_reaches_the_page_only_with_passwordless_console(self, mock_wvm):
        # without the permission noVNC asks for the password; the page must not hold it
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_passwd.return_value = None
        mock_conn.get_console_passwd.return_value = "vncpw7f3a"
        mock_wvm.return_value = mock_conn
        permission = Permission.objects.get(codename="passwordless_console")

        for user, holds in ((self.alice, False), (self.alice, True), (self.admin_user, True)):
            if holds and not user.is_superuser:
                user.user_permissions.add(permission)
            with self.subTest(user=user.username, permission=holds):
                self.client.force_login(get_user_model().objects.get(pk=user.pk))  # fresh permission cache
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual("vncpw7f3a" in response.content.decode(), holds)

    def test_console_unauthorized_user_forbidden(self):
        self.client.force_login(self.bob)
        url = self.url
        response = self.client.get(url)

        # Non-permitted user attempting to view other user's instance: the
        # console's own error page, without the VM's name or a console token
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "console-error.html")
        self.assertIn("permission", response.content.decode("utf-8").lower())
        self.assertNotContains(response, "vm-alpha", status_code=403)
        self.assertNotIn("token", response.context)

    @override_settings(SERIAL_CONSOLE_ENABLED=False)
    @patch("console.views.wvmInstance")
    def test_a_console_that_cannot_open_gets_no_console_client(self, mock_wvm):
        # the page says why; it neither connects to novncd nor offers keys
        conn = mock_wvm.return_value
        conn.instance.isActive.return_value = 1
        self.client.force_login(self.admin_user)
        for console_type, running in (("vnc", 0), ("pty", 1), ("rdp", 1), (None, 1)):
            with self.subTest(console_type=console_type, running=running):
                conn.get_console_type.return_value = console_type
                conn.instance.isActive.return_value = running
                response = self.client.get(self.url)
                self.assertTemplateUsed(response, "console-error.html")
                self.assertNotIn("token", response.context)
                page = html.fromstring(response.content)
                self.assertEqual(page.xpath("//script[@type='module'] | //*[@id='dropdownMenuLink']"), [])
                self.assertEqual(len(page.xpath("//div[@role='alert']")), 1)
                self.assertEqual(page.findtext(".//title"), "vm-alpha - Console")

    @patch("console.views.wvmInstance")
    def test_the_vnc_page_carries_the_signed_token(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_passwd.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        response = self.client.get(self.url)

        signed = vnc_config(response)["token"]
        self.assertEqual(TimestampSigner(salt="console.novnc").unsign(signed),
                         f"{self.compute.id}:{self.instance.uuid}:{self.admin_user.id}")

    @patch("console.views.wvmInstance")
    def test_a_shut_off_vm_says_so(self, mock_wvm):
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_passwd.return_value = None
        mock_wvm.return_value.instance.isActive.return_value = 0
        self.client.force_login(self.alice)
        response = self.client.get(self.url)
        self.assertContains(response, "The VM is not running")

    @patch("console.views.wvmInstance")
    def test_the_vnc_page_connects_only_to_the_servers_proxy(self, mock_wvm):
        # a link naming another host would send it the signed console token;
        # nginx proxies /novncd/ on the panel's own scheme, host and port
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_passwd.return_value = None
        self.client.force_login(self.alice)
        response = self.client.get(self.url + "?host=attacker.example&port=443&path=x&password=x")
        self.assertNotContains(response, "attacker.example")
        self.assertEqual(set(vnc_config(response)), {"token", "password", "resize", "clip", "viewOnly"})
        script = (Path(settings.BASE_DIR) / "static/js/console_vnc.js").read_text()
        self.assertIn("scheme + window.location.host + '/novncd/?token='", script)

    @patch("console.views.wvmInstance")
    def test_the_vnc_page_offers_each_keyboard_layout_file(self, mock_wvm):
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_passwd.return_value = None
        self.client.force_login(self.alice)
        response = self.client.get(self.url)
        layouts = json.loads(html.fromstring(response.content).get_element_by_id("keyboard-layouts").text)
        files = sorted(path.stem for path in LAYOUTS_DIR.glob("*.json"))
        self.assertEqual(sorted(layouts), files)
        self.assertEqual(next(iter(layouts)), "us")
        for layout_id, layout in layouts.items():
            self.assertContains(response, f'<option value="{layout_id}">{layout["name"]}</option>', html=True)

    @patch("console.views.wvmInstance")
    def test_the_vnc_page_starts_as_the_console_settings_say(self, mock_wvm):
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_passwd.return_value = None
        self.client.force_login(self.alice)
        names = ("CONSOLE_SCALE", "CONSOLE_RESIZE_SESSION", "CONSOLE_CLIP_VIEWPORT", "CONSOLE_VIEW_ONLY")
        for values, resize, clip, view_only in (
            (("False", "False", "False", "False"), "off", False, False),
            (("True", "False", "True", "True"), "scale", True, True),
            (("True", "True", "False", "False"), "remote", False, False),
        ):
            with self.subTest(values=values):
                for name, value in zip(names, values):
                    AppSettings.objects.filter(key=name).update(value=value)
                config = vnc_config(self.client.get(self.url))
                self.assertEqual((config["resize"], config["clip"], config["viewOnly"]), (resize, clip, view_only))

    @patch("console.views.wvmInstance")
    def test_the_vnc_password_stays_data_in_the_page(self, mock_wvm):
        # json_script: no quote or tag in it ends the script element
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_passwd.return_value = None
        mock_wvm.return_value.get_console_passwd.return_value = "O'B</script><script>x()&"
        self.client.force_login(self.admin_user)
        response = self.client.get(self.url)
        self.assertNotContains(response, "</script><script>x()")
        self.assertEqual(vnc_config(response)["password"], "O'B</script><script>x()&")
    @patch("console.views.wvmInstance")
    def test_the_page_sets_no_token_cookie(self, mock_wvm):
        # one cookie for every tab would name the last console opened
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_passwd.return_value = None
        self.client.force_login(self.admin_user)
        response = self.client.get(self.url)
        self.assertNotIn("token", response.cookies)

    @patch("console.views.wvmInstance")
    def test_console_view_instances_perm_does_not_open_console(self, mock_wvm):
        # Global view_instances is a read-only role; the console
        # is for superusers and VM owners only.
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_passwd.return_value = None
        mock_wvm.return_value = mock_conn

        perm = Permission.objects.get(codename="view_instances")
        self.bob.user_permissions.add(perm)

        self.client.force_login(self.bob)
        url = self.url
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertTemplateNotUsed(response, "console-vnc.html")

    @patch("console.views.wvmInstance")
    def test_a_tcp_hosts_loopback_console_says_why_it_cannot_open(self, mock_wvm):
        # the running VM's listener decides, as for novncd, not its next-start settings
        Compute.objects.filter(pk=self.compute.pk).update(type=1)
        conn = mock_wvm.return_value
        conn.get_console_type.return_value = "vnc"
        conn.get_console_passwd.return_value = None
        conn.get_console_socket.return_value = None
        conn.console_listens_locally.return_value = False  # next start: all interfaces
        self.client.force_login(self.admin_user)
        for live, refused in (("127.0.0.1", True), ("::1", True), ("0.0.0.0", False), ("192.0.2.40", False)):
            with self.subTest(live=live):
                conn.get_console_listener_addr.return_value = live
                response = self.client.get(self.url)
                self.assertEqual("This console listens only on its host" in response.content.decode(), refused)

    @patch("console.views.wvmInstance")
    def test_console_libvirt_error_fallback(self, mock_wvm):
        mock_wvm.side_effect = libvirtError("Connection to libvirtd failed")

        self.client.force_login(self.admin_user)
        url = self.url
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-error.html")
        self.assertIsNotNone(response.context["console_error"])

    def test_an_unknown_vm_gives_the_superuser_an_error_page(self):
        self.client.force_login(self.admin_user)
        url = reverse("console", args=[self.compute.id, "no-such-uuid"])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "console-error.html")
        self.assertIsNotNone(response.context["console_error"])

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    @patch("console.views.wvmInstance")
    def test_the_serial_console_offers_only_the_keys_a_terminal_takes(self, mock_wvm):
        mock_wvm.return_value.get_console_type.return_value = "pty"
        self.client.force_login(self.admin_user)
        page = html.fromstring(self.client.get(self.url).content)
        keys = page.xpath("//*[@aria-labelledby='dropdownMenuLink']//a/@id")
        self.assertEqual(sorted(keys), ["ctrlbackslash", "ctrlc", "ctrld", "ctrlz", "sendesc", "sendtab"])

    @patch("console.views.wvmInstance")
    def test_console_send_keys_menu_elements(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_passwd.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        expected_ids = [
            "ctrlaltdel",
            "ctrlaltbackspace",
            "alttab",
            "superkey",
            "sendesc",
            "sendtab",
            "ctrlc",
            "ctrlz",
            "ctrld",
            "ctrlbackslash",
            "holdctrl",
            "holdalt",
            "holdsuper",
        ] + [f"ctrlaltf{i}" for i in range(1, 13)]

        for key_id in expected_ids:
            self.assertIn(
                f'id="{key_id}"',
                content,
                f"Expected key element id '{key_id}' in console menu",
            )


class NovncdDaemonLogicTestCase(TestCase):
    def setUp(self):
        self.get_parser = novncd_mod.get_parser
        self.ConsoleClient = novncd_mod.ConsoleClient

    def test_novncd_parser_defaults(self):
        parser = self.get_parser()
        opts = parser.parse_args([])
        self.assertFalse(opts.verbose)
        self.assertFalse(opts.debug)
        self.assertEqual(opts.port, 6080)

    def test_novncd_parser_custom_arguments(self):
        parser = self.get_parser()
        opts = parser.parse_args(["-v", "-d", "-H", "192.168.1.100", "-p", "7070"])
        self.assertTrue(opts.verbose)
        self.assertTrue(opts.debug)
        self.assertEqual(opts.host, "192.168.1.100")
        self.assertEqual(opts.port, 7070)

    @patch.object(novncd_mod, "get_connection_infos")
    def test_a_cookie_does_not_choose_the_console(self, mock_get_info):
        # another tab's console in a cookie: the URL's own token is used
        mock_get_info.return_value = ("host1", "root", 1, "192.168.1.50", 5900, None)
        handler = self.ConsoleClient()
        handler.headers = {"cookie": "token=1-uuid-of-another-tab"}
        handler.path = "/novncd/?token=1-uuid-of-this-tab"
        handler.msg = MagicMock()
        handler.do_proxy = MagicMock()
        handler._new_client(socket_factory=MagicMock())
        mock_get_info.assert_called_once_with("1-uuid-of-this-tab")

    @patch.object(novncd_mod, "get_connection_infos")
    def test_compatibility_mixin_token_from_query_params(self, mock_get_info):
        mock_get_info.return_value = (
            "host2",
            "root",
            1,
            "192.168.1.50",
            5901,
            None,
        )

        handler = self.ConsoleClient()
        handler.headers = {}
        handler.path = "/novncd/?token=1-uuid-from-query"
        handler.msg = MagicMock()
        handler.do_proxy = MagicMock()

        socket_factory = MagicMock()
        handler._new_client(socket_factory=socket_factory)

        mock_get_info.assert_called_once_with("1-uuid-from-query")
        # the address the console listens on
        socket_factory.assert_called_once_with("192.168.1.50", 5901, connect=True)

    @patch.object(novncd_mod, "get_connection_infos")
    def test_a_local_socket_host_reaches_a_console_on_its_loopback(self, mock_get_info):
        # libvirt on the panel's host, the VM's console listening on 127.0.0.1
        mock_get_info.return_value = ("localhost", "", novncd_mod.CONN_SOCKET, "127.0.0.1", 5902, None)
        handler = self.ConsoleClient()
        handler.headers = {}
        handler.path = "/novncd/?token=1-uuid"
        handler.msg = MagicMock()
        handler.do_proxy = MagicMock()
        socket_factory = MagicMock()
        handler._new_client(socket_factory=socket_factory)
        socket_factory.assert_called_once_with("127.0.0.1", 5902, connect=True)

    def test_an_ssh_hosts_console_always_goes_through_the_tunnel(self):
        # whatever address the console listens on, the VNC stream is not sent unencrypted
        for console_host, console_socket, target in (
            ("192.0.2.40", None, "192.0.2.40:5900"),
            ("0.0.0.0", None, "127.0.0.1:5900"),
            ("::", None, "[::1]:5900"),
            ("127.0.0.1", None, "127.0.0.1:5900"),
            (None, "/run/libvirt/qemu/vnc.sock", "/run/libvirt/qemu/vnc.sock"),
        ):
            with self.subTest(console_host=console_host), patch.object(
                novncd_mod, "get_connection_infos",
                return_value=("kvm1.example.com", "root", novncd_mod.CONN_SSH, console_host, 5900, console_socket),
            ), patch.object(novncd_mod, "open_tunnel", return_value=(MagicMock(), MagicMock())) as open_tunnel:
                handler = self.ConsoleClient()
                handler.path = "/novncd/?token=1-uuid"
                handler.msg = MagicMock()
                handler.do_proxy = MagicMock()
                socket_factory = MagicMock()
                handler._new_client(socket_factory=socket_factory)
                open_tunnel.assert_called_once_with("kvm1.example.com", "root", target)
                socket_factory.assert_not_called()
                # the tunnel ends with the session
                open_tunnel.return_value[1].close.assert_called_once_with()

    def test_a_tcp_hosts_console_is_reached_where_it_listens(self):
        for console_host, reached in (("0.0.0.0", "kvm1.example.com"), ("::", "kvm1.example.com"),
                                      (None, "kvm1.example.com"), ("192.0.2.40", "192.0.2.40")):
            with self.subTest(console_host=console_host), patch.object(
                novncd_mod, "get_connection_infos",
                return_value=("kvm1.example.com", "", 1,
                              console_host, 5900, None),
            ):
                handler = self.ConsoleClient()
                handler.path = "/novncd/?token=1-uuid"
                handler.msg = MagicMock()
                handler.do_proxy = MagicMock()
                socket_factory = MagicMock()
                handler._new_client(socket_factory=socket_factory)
                socket_factory.assert_called_once_with(reached, 5900, connect=True)

    def test_a_tcp_hosts_loopback_console_is_refused(self):
        for console_host in ("127.0.0.1", "::1", "localhost"):
            with self.subTest(console_host=console_host), patch.object(
                novncd_mod, "get_connection_infos", return_value=("kvm1.example.com", "", 1, console_host, 5900, None),
            ):
                handler = self.ConsoleClient()
                handler.path = "/novncd/?token=1-uuid"
                handler.msg = MagicMock()
                socket_factory = MagicMock()
                with self.assertRaises(Exception):
                    handler._new_client(socket_factory=socket_factory)
                socket_factory.assert_not_called()

    @patch.object(novncd_mod, "get_connection_infos")
    def test_compatibility_mixin_missing_token_safe_exit(self, mock_get_info):
        handler = self.ConsoleClient()
        handler.headers = {}
        handler.path = "/novncd/"
        handler.msg = MagicMock()

        socket_factory = MagicMock()
        # a refusal is a warning: it shows in the log without -v
        with self.assertLogs(level="WARNING") as log:
            handler._new_client(socket_factory=socket_factory)

        mock_get_info.assert_not_called()
        socket_factory.assert_not_called()
        self.assertIn("without a token", log.output[0])

    @patch("console.tokens.authorize")
    @patch("vrtManager.instance.wvmInstance")
    def test_get_connection_infos_valid_signed_token(self, mock_wvm, mock_inst_get):
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        mock_instance = MagicMock()
        mock_instance.compute.hostname = "127.0.0.1"
        mock_instance.compute.login = "root"
        mock_instance.compute.password = ""
        mock_instance.compute.type = 1
        mock_instance.name = "test-vm"
        mock_inst_get.return_value = (mock_instance, user)

        mock_conn = MagicMock()
        mock_conn.get_console_listener_addr.return_value = "127.0.0.1"
        mock_conn.get_console_port.return_value = 5900
        mock_conn.get_console_socket.return_value = None
        mock_wvm.return_value = mock_conn

        signer = TimestampSigner(salt="console.novnc")
        token = signer.sign(f"1:test-uuid:{user.id}")

        infos = novncd_mod.get_connection_infos(token)
        self.assertEqual(infos[0], "127.0.0.1")
        self.assertEqual(infos[4], 5900)
        # the VM access was checked for, not whichever VM has its name now
        self.assertEqual(mock_wvm.call_args.kwargs["uuid"], mock_instance.uuid)

    @patch("sys.argv", ["novncd"])
    @override_settings(DEBUG=False)
    def test_get_connection_infos_invalid_token_in_production(self):
        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos("invalid-raw-token")

    def test_get_connection_infos_unauthorized_user(self):
        User = get_user_model()
        unauthorized_user = User.objects.create_user(
            username="unauthorized_console_user",
            password="password",
        )
        compute = Compute.objects.create(
            name="novnc-unauth-compute",
            hostname="127.0.0.1",
            login="root",
            password="",
            type=1,
        )
        instance = Instance.objects.create(
            compute=compute,
            name="novnc-unauth-vm",
            uuid="33333333-3333-3333-3333-333333333333",
        )

        signer = TimestampSigner(salt="console.novnc")
        token = signer.sign(f"{compute.id}:{instance.uuid}:{unauthorized_user.id}")

        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos(token)

    def test_get_connection_infos_rejects_signed_token_without_user(self):
        # The console view always signs host:uuid:user_id; a token without the
        # user part would skip the per-user access check entirely.
        compute = Compute.objects.create(
            name="novnc-2part-compute", hostname="127.0.0.1", login="root", password="", type=1
        )
        instance = Instance.objects.create(
            compute=compute,
            name="novnc-2part-vm",
            uuid="66666666-6666-6666-6666-666666666666",
        )
        signer = TimestampSigner(salt="console.novnc")
        token = signer.sign(f"{compute.id}:{instance.uuid}")

        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos(token)

    def test_get_connection_infos_rejects_unsigned_token_even_under_test_runner(self):
        # sys.argv contains "test" while this suite runs; production code must
        # not change behaviour based on that.
        compute = Compute.objects.create(
            name="novnc-unsigned-compute", hostname="127.0.0.1", login="root", password="", type=1
        )
        instance = Instance.objects.create(
            compute=compute,
            name="novnc-unsigned-vm",
            uuid="88888888-8888-8888-8888-888888888888",
        )

        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos(f"{compute.id}-{instance.uuid}")

    def test_get_connection_infos_view_instances_user_is_not_enough(self):
        User = get_user_model()
        viewer = User.objects.create_user(username="novnc_viewer", password="password")
        viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        compute = Compute.objects.create(
            name="novnc-viewer-compute", hostname="127.0.0.1", login="root", password="", type=1
        )
        instance = Instance.objects.create(
            compute=compute,
            name="novnc-viewer-vm",
            uuid="55555555-5555-5555-5555-555555555555",
        )

        signer = TimestampSigner(salt="console.novnc")
        token = signer.sign(f"{compute.id}:{instance.uuid}:{viewer.id}")

        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos(token)

    def test_get_connection_infos_inactive_user(self):
        User = get_user_model()
        inactive_user = User.objects.create_user(
            username="inactive_console_user",
            password="password",
            is_active=False,
        )
        compute = Compute.objects.create(
            name="novnc-inactive-compute",
            hostname="127.0.0.1",
            login="root",
            password="",
            type=1,
        )
        instance = Instance.objects.create(
            compute=compute,
            name="novnc-inactive-vm",
            uuid="44444444-4444-4444-4444-444444444444",
        )
        UserInstance.objects.create(instance=instance, user=inactive_user)

        signer = TimestampSigner(salt="console.novnc")
        token = signer.sign(f"{compute.id}:{instance.uuid}:{inactive_user.id}")

        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos(token)

    @patch("sys.argv", ["novncd"])
    @override_settings(DEBUG=True)
    def test_get_connection_infos_debug_true_does_not_bypass(self):
        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos("invalid-token-in-debug")

    @patch("sys.argv", ["novncd"])
    def test_get_connection_infos_expired_token(self):
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        compute = Compute.objects.create(
            name="novnc-expired-compute",
            hostname="127.0.0.1",
            login="root",
            password="",
            type=1,
        )
        instance = Instance.objects.create(
            compute=compute,
            name="novnc-expired-vm",
            uuid="55555555-5555-5555-5555-555555555555",
        )

        import time
        from unittest.mock import patch
        # Sign token 300 seconds in the past (> 120s TTL)
        with patch("time.time", return_value=time.time() - 300):
            signer = TimestampSigner(salt="console.novnc")
            expired_token = signer.sign(f"{compute.id}:{instance.uuid}:{user.id}")

        with self.assertRaises(PermissionError):
            novncd_mod.get_connection_infos(expired_token)
