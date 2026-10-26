# pylint: disable=no-member
import importlib.machinery
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.signing import TimestampSigner
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escapejs
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

        cls.compute = Compute.objects.create(
            name="test-compute",
            hostname="127.0.0.1",
            login="root",
            password="",
            type=1,
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

        cls.token = f"{cls.compute.id}-{cls.instance.uuid}"

    @patch("console.views.wvmInstance")
    def test_console_superuser_vnc_lite(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = None
        mock_conn.get_console_passwd.return_value = "vncsecret"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}&view=lite"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc-lite.html")
        signer = TimestampSigner(salt="console.novnc")
        unsigned = signer.unsign(response.context["token"], max_age=120)
        self.assertEqual(
            unsigned, f"{self.compute.id}:{self.instance.uuid}:{self.admin_user.id}"
        )
        self.assertEqual(response.context["ws_path"], "novncd/")
        self.assertEqual(response.context["ws_port"], 6080)
        self.assertEqual(response.context["console_passwd"], "vncsecret")

    @patch("console.views.wvmInstance")
    def test_console_superuser_vnc_full(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = 5900
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}&view=full"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc-full.html")
        self.assertEqual(response.context["ws_port"], 5900)

    @patch("console.views.wvmInstance")
    def test_the_lite_console_switches_scaling_from_its_menu(self, mock_wvm):
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_websocket_port.return_value = None
        self.client.force_login(self.admin_user)
        for query, pressed in (("", "false"), ("&scale=true", "true")):
            with self.subTest(query=query):
                page = html.fromstring(self.client.get(reverse("console") + f"?token={self.token}&view=lite{query}").content)
                switch = page.xpath("//*[@id='scale_button']//a")[0]
                self.assertEqual(switch.get("aria-pressed"), pressed)
                self.assertEqual("active" in switch.get("class").split(), pressed == "true")
        page = html.fromstring(self.client.get(reverse("console") + f"?token={self.token}&view=full").content)
        self.assertEqual(page.xpath("//*[@id='scale_button']"), [])  # noVNC's own settings scale the full view

    @patch("console.views.wvmInstance")
    def test_console_unsupported_graphics_type(self, mock_wvm):
        # Only VNC is supported; a VM defined elsewhere may use another type.
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "rdp"
        mock_conn.get_console_websocket_port.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}&view=full"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc-lite.html")
        self.assertIn("'rdp' is not supported", str(response.context["console_error"]))

    @override_settings(SERIAL_CONSOLE_ENABLED=True)
    @patch("console.views.wvmInstance")
    def test_console_superuser_pty(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "pty"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-xterm.html")

    @override_settings(SERIAL_CONSOLE_ENABLED=False)
    @patch("console.views.wvmInstance")
    def test_console_pty_refused_when_serial_console_disabled(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "pty"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}"
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
        mock_conn.get_console_websocket_port.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.alice)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc-lite.html")

    @patch("console.views.wvmInstance")
    def test_the_console_password_reaches_the_page_only_with_passwordless_console(self, mock_wvm):
        # without the permission noVNC asks for the password; the page must not hold it
        # (letters and digits only: escapejs keeps them as they are in the lite view)
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = None
        mock_conn.get_console_passwd.return_value = "vncpw7f3a"
        mock_wvm.return_value = mock_conn
        permission = Permission.objects.get(codename="passwordless_console")

        for user, holds in ((self.alice, False), (self.alice, True), (self.admin_user, True)):
            if holds and not user.is_superuser:
                user.user_permissions.add(permission)
            for view in ("lite", "full"):
                with self.subTest(user=user.username, permission=holds, view=view):
                    self.client.force_login(get_user_model().objects.get(pk=user.pk))  # fresh permission cache
                    response = self.client.get(reverse("console") + f"?token={self.token}&view={view}")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual("vncpw7f3a" in response.content.decode(), holds)

    def test_console_unauthorized_user_forbidden(self):
        self.client.force_login(self.bob)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        # Non-permitted user attempting to view other user's instance
        self.assertEqual(response.status_code, 403)
        self.assertIn("permission", response.content.decode("utf-8").lower())

    @patch("console.views.wvmInstance")
    def test_console_lite_uses_the_signed_token_not_the_url_token(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("console") + f"?token={self.token}")

        signed = response.context["token"]
        self.assertNotEqual(signed, self.token)
        self.assertNotContains(response, "readQueryVariable('token'")
        self.assertContains(response, f"const token = '{escapejs(signed)}'")

    @patch("console.views.wvmInstance")
    def test_a_shut_off_vm_says_so(self, mock_wvm):
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.instance.isActive.return_value = 0
        self.client.force_login(self.alice)
        response = self.client.get(reverse("console") + f"?token={self.token}")
        self.assertContains(response, "The VM is not running")

    @patch("console.views.wvmInstance")
    def test_the_lite_console_connects_only_to_the_servers_proxy(self, mock_wvm):
        # a link naming another host would send it the signed console token
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_websocket_port.return_value = None
        self.client.force_login(self.alice)
        response = self.client.get(reverse("console") + f"?token={self.token}&host=attacker.example&port=443&path=x")
        self.assertNotContains(response, "attacker.example")
        for name in ("host", "port", "path"):
            self.assertNotContains(response, f"readQueryVariable('{name}'")
        self.assertContains(response, "const host = 'testserver';")

    @patch("console.views.wvmInstance")
    def test_the_page_sets_no_token_cookie(self, mock_wvm):
        # one cookie for every tab would name the last console opened
        mock_wvm.return_value.get_console_type.return_value = "vnc"
        mock_wvm.return_value.get_console_websocket_port.return_value = None
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("console") + f"?token={self.token}")
        self.assertNotIn("token", response.cookies)

    @patch("console.views.wvmInstance")
    def test_console_view_instances_perm_does_not_open_console(self, mock_wvm):
        # Global view_instances is a read-only role; the console
        # is for superusers and VM owners only.
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = None
        mock_wvm.return_value = mock_conn

        perm = Permission.objects.get(codename="view_instances")
        self.bob.user_permissions.add(perm)

        self.client.force_login(self.bob)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertTemplateNotUsed(response, "console-vnc-lite.html")

    @patch("console.views.wvmInstance")
    @override_settings(WS_PUBLIC_PATH="/novncd/")
    def test_console_ws_path_normalization_leading_slash(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ws_path"], "novncd/")

    @patch("console.views.wvmInstance")
    @override_settings(WS_PUBLIC_PATH="novncd/")
    def test_console_ws_path_normalization_clean(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ws_path"], "novncd/")

    @patch("console.views.wvmInstance")
    @override_settings(WS_PUBLIC_PATH="/")
    def test_console_ws_path_root_slash(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ws_path"], "")

    @override_settings(ALLOWED_HOSTS=["panel.example.com"])
    @patch("console.views.wvmInstance")
    def test_console_ws_host_strip_port(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url, HTTP_HOST="panel.example.com:8080")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ws_host"], "panel.example.com")

    @patch("console.views.wvmInstance")
    def test_console_xss_protection_query_parameters(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        # Attempt XSS injection via query parameters
        url = (
            reverse("console")
            + f"?token={self.token}"
            + "&view=lite&view_only=alert('xss')&scale=true&clip_viewport=1"
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["view_only"], False)
        self.assertEqual(response.context["scale"], True)
        self.assertEqual(response.context["clip_viewport"], True)

        content = response.content.decode("utf-8")
        self.assertNotIn("alert('xss')", content)
        self.assertIn("rfb.viewOnly = false;", content)
        self.assertIn("rfb.scaleViewport = true;", content)

    @patch("console.views.wvmInstance")
    def test_console_password_escapejs_escaping(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = None
        mock_conn.get_console_passwd.return_value = "O'Brian<script>&123"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)

        # Test Lite mode
        url_lite = reverse("console") + f"?token={self.token}&view=lite"
        resp_lite = self.client.get(url_lite)
        self.assertEqual(resp_lite.status_code, 200)
        content_lite = resp_lite.content.decode("utf-8")
        self.assertIn(r"O\u0027Brian", content_lite)
        self.assertNotIn("&#39;", content_lite)

        # Test Full mode
        url_full = reverse("console") + f"?token={self.token}&view=full"
        resp_full = self.client.get(url_full)
        self.assertEqual(resp_full.status_code, 200)
        content_full = resp_full.content.decode("utf-8")
        # In script tag, password must use JS unicode escape and not HTML entities
        main_script_block = [
            s.split("</script>")[0]
            for s in content_full.split("<script")
            if "defaults" in s
        ][0]
        self.assertIn(r"password: 'O\u0027Brian", main_script_block)
        self.assertNotIn("&#39;", main_script_block)
        self.assertNotIn("&#x27;", main_script_block)

    @patch("console.views.wvmInstance")
    def test_console_full_resize_syntax_validity(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_conn.get_console_websocket_port.return_value = None
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)

        # Default: scale=False, resize_session=False -> 'off'
        url = reverse("console") + f"?token={self.token}&view=full"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn("resize: 'off',", content)
        self.assertNotIn("&#x27;off&#x27;", content)
        self.assertNotIn("&#39;off&#39;", content)

        # scale=True, resize_session=False -> 'scale'
        url_scale = reverse("console") + f"?token={self.token}&view=full&scale=true"
        resp_scale = self.client.get(url_scale)
        self.assertEqual(resp_scale.status_code, 200)
        content_scale = resp_scale.content.decode("utf-8")
        self.assertIn("resize: 'scale',", content_scale)

        # resize_session=True -> 'remote'
        url_remote = (
            reverse("console") + f"?token={self.token}&view=full&resize_session=true"
        )
        resp_remote = self.client.get(url_remote)
        self.assertEqual(resp_remote.status_code, 200)
        content_remote = resp_remote.content.decode("utf-8")
        self.assertIn("resize: 'remote',", content_remote)

    @patch("console.views.wvmInstance")
    def test_console_libvirt_error_fallback(self, mock_wvm):
        mock_wvm.side_effect = libvirtError("Connection to libvirtd failed")

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc-lite.html")
        self.assertIsNotNone(response.context["console_error"])

    def test_console_missing_token_safe_fallback(self):
        self.client.force_login(self.admin_user)
        url = reverse("console")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "console-vnc-lite.html")
        self.assertIsNotNone(response.context["console_error"])

    @patch("console.views.wvmInstance")
    def test_console_send_keys_menu_elements(self, mock_wvm):
        mock_conn = MagicMock()
        mock_conn.get_console_type.return_value = "vnc"
        mock_wvm.return_value = mock_conn

        self.client.force_login(self.admin_user)
        url = reverse("console") + f"?token={self.token}&view=lite"
        response = self.client.get(url)

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
        self.CompatibilityMixIn = novncd_mod.CompatibilityMixIn

    def test_novncd_parser_defaults(self):
        parser = self.get_parser()
        opts = parser.parse_args([])
        self.assertFalse(opts.verbose)
        self.assertFalse(opts.debug)
        self.assertEqual(opts.port, 6080)

    def test_novncd_parser_custom_arguments(self):
        parser = self.get_parser()
        opts = parser.parse_args(
            ["-v", "-d", "-H", "192.168.1.100", "-p", "7070", "-c", "/path/to/cert.pem"]
        )
        self.assertTrue(opts.verbose)
        self.assertTrue(opts.debug)
        self.assertEqual(opts.host, "192.168.1.100")
        self.assertEqual(opts.port, 7070)
        self.assertEqual(opts.cert, "/path/to/cert.pem")

    @patch.object(novncd_mod, "get_connection_infos")
    def test_a_cookie_does_not_choose_the_console(self, mock_get_info):
        # another tab's console in a cookie: the URL's own token is used
        mock_get_info.return_value = ("host1", "root", 1, "192.168.1.50", 5900, None)
        handler = self.CompatibilityMixIn()
        handler.headers = {"cookie": "token=1-uuid-of-another-tab"}
        handler.path = "/novncd/?token=1-uuid-of-this-tab"
        handler.msg = MagicMock()
        handler.do_proxy = MagicMock()
        handler.verbose = False
        handler._new_client(daemon=False, socket_factory=MagicMock())
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

        handler = self.CompatibilityMixIn()
        handler.headers = {}
        handler.path = "/novncd/?token=1-uuid-from-query"
        handler.msg = MagicMock()
        handler.do_proxy = MagicMock()
        handler.verbose = False

        socket_factory = MagicMock()
        handler._new_client(daemon=False, socket_factory=socket_factory)

        mock_get_info.assert_called_once_with("1-uuid-from-query")
        socket_factory.assert_called_once_with("host2", 5901, connect=True)

    @patch.object(novncd_mod, "get_connection_infos")
    def test_a_local_socket_host_reaches_a_console_on_its_loopback(self, mock_get_info):
        # libvirt on the panel's host, the VM's console listening on 127.0.0.1
        mock_get_info.return_value = ("localhost", "", novncd_mod.CONN_SOCKET, "127.0.0.1", 5902, None)
        handler = self.CompatibilityMixIn()
        handler.headers = {}
        handler.path = "/novncd/?token=1-uuid"
        handler.msg = MagicMock()
        handler.do_proxy = MagicMock()
        handler.verbose = False
        socket_factory = MagicMock()
        handler._new_client(daemon=False, socket_factory=socket_factory)
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
            ), patch.object(novncd_mod, "open_tunnel", return_value=(MagicMock(), MagicMock())) as open_tunnel, \
                    patch.object(novncd_mod, "close_tunnel", return_value="") as close_tunnel:
                handler = self.CompatibilityMixIn()
                handler.path = "/novncd/?token=1-uuid"
                handler.msg = MagicMock()
                handler.do_proxy = MagicMock()
                handler.verbose = False
                socket_factory = MagicMock()
                handler._new_client(daemon=False, socket_factory=socket_factory)
                open_tunnel.assert_called_once_with("kvm1.example.com", "root", target)
                socket_factory.assert_not_called()
                # the tunnel ends with the session
                close_tunnel.assert_called_once_with(open_tunnel.return_value[1])

    @patch.object(novncd_mod, "get_connection_infos")
    def test_compatibility_mixin_missing_token_safe_exit(self, mock_get_info):
        handler = self.CompatibilityMixIn()
        handler.headers = {}
        handler.path = "/novncd/"
        handler.msg = MagicMock()

        socket_factory = MagicMock()
        # Should cleanly exit and log message without raising UnboundLocalError
        handler._new_client(daemon=False, socket_factory=socket_factory)

        mock_get_info.assert_not_called()
        socket_factory.assert_not_called()
        handler.msg.assert_called_with("No console token in the websocket URL")

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
