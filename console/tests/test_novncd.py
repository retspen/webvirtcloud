"""novncd, the VNC console proxy: what it checks before it connects a browser, and a
port it cannot listen on ends it with a failure status, which systemd restarts."""

import socket
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase
from unittest.mock import MagicMock, patch
from accounts.models import UserInstance
from computes.models import Compute
from console import tokens
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.signing import TimestampSigner
from django.conf import settings
from django.test import TestCase, override_settings
from instances.models import Instance
from console.tests.daemons import novncd_mod

ROOT = Path(__file__).resolve().parent.parent.parent


class NovncdExitTestCase(SimpleTestCase):
    def test_a_taken_port_ends_novncd_with_a_failure_status(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            novncd = subprocess.run([sys.executable, str(ROOT / "console" / "novncd"), "-v", "-H", "127.0.0.1",
                                     "-p", str(port)], cwd=ROOT, capture_output=True, timeout=60)
        self.assertNotEqual(novncd.returncode, 0)
        self.assertIn(b"Openening socket failed", novncd.stderr)


class NovncdDaemonLogicTestCase(TestCase):
    def setUp(self):
        self.get_parser = novncd_mod.get_parser
        self.ConsoleClient = novncd_mod.ConsoleClient
        user = MagicMock(pk=7)
        user.username = "vnc-user"
        for name, value in (("authorize", (MagicMock(), user)), ("session_user_id", "7")):
            patcher = patch.object(novncd_mod, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(novncd_mod.ConsoleClient, "headers", {}, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

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
        self.authorize.assert_called_once_with("1-uuid-of-this-tab", "vnc")

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

        self.authorize.assert_called_once_with("1-uuid-from-query", "vnc")
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

    @patch("vrtManager.instance.wvmInstance")
    def test_get_connection_infos_reads_the_vm_it_was_given(self, mock_wvm):
        mock_instance = MagicMock()
        mock_instance.compute.hostname = "127.0.0.1"
        mock_instance.compute.login = "root"
        mock_instance.compute.password = ""
        mock_instance.compute.type = 1
        mock_instance.name = "test-vm"

        mock_conn = MagicMock()
        mock_conn.get_console_listener_addr.return_value = "127.0.0.1"
        mock_conn.get_console_port.return_value = 5900
        mock_conn.get_console_socket.return_value = None
        mock_wvm.return_value = mock_conn

        infos = novncd_mod.get_connection_infos(mock_instance)
        self.assertEqual(infos[0], "127.0.0.1")
        self.assertEqual(infos[4], 5900)
        # the VM access was checked for, not whichever VM has its name now
        self.assertEqual(mock_wvm.call_args.kwargs["uuid"], mock_instance.uuid)

    def test_the_vnc_server_is_waited_for_a_bounded_time(self):
        with patch.object(novncd_mod.socket, "create_connection") as create_connection:
            tsock = novncd_mod.bounded_connect("192.0.2.40", 5900, connect=True)
        create_connection.assert_called_once_with(("192.0.2.40", 5900), timeout=novncd_mod.CONNECT_TIMEOUT)
        tsock.settimeout.assert_called_once_with(None)

    def test_a_token_without_its_users_session_is_refused_and_logged(self):
        from logs.models import Logs

        self.session_user_id.return_value = None  # read from a log, used in another browser
        handler = self.ConsoleClient()
        handler.headers = {"Cookie": "sessionid=another", "X-Real-IP": "192.0.2.9"}
        handler.path = "/novncd/?token=1-uuid"
        handler.msg = MagicMock()
        socket_factory = MagicMock()
        with patch.object(novncd_mod, "get_connection_infos") as get_info, self.assertLogs(level="WARNING"):
            handler._new_client(socket_factory=socket_factory)
        get_info.assert_not_called()
        socket_factory.assert_not_called()
        self.session_user_id.assert_called_once_with("sessionid=another")
        row = Logs.objects.get()
        self.assertEqual((row.user, row.ip, row.success), ("vnc-user", "192.0.2.9", False))
        self.assertEqual(row.message, "VNC console refused: The console page was opened in another session")

    def test_the_session_names_its_user(self):
        from django.contrib.sessions.backends.db import SessionStore

        user = get_user_model().objects.create_user("vnc-session", password="pw")
        self.client.force_login(user)
        cookie = f"{settings.SESSION_COOKIE_NAME}={self.client.session.session_key}; other=1"
        self.assertEqual(tokens.session_user_id(cookie), str(user.pk))
        self.assertIsNone(tokens.session_user_id(f"{settings.SESSION_COOKIE_NAME}={SessionStore().session_key}"))
        self.assertIsNone(tokens.session_user_id(None))

    def test_a_vnc_session_ends_when_its_user_may_no_longer_open_it(self):
        tsock, ended = MagicMock(), MagicMock()
        ended.wait.return_value = False  # ACCESS_CHECK passed, the session still open
        vm = MagicMock()
        with patch.object(novncd_mod, "may_still_open", side_effect=[True, False]) as may_still_open:
            novncd_mod.end_when_refused(vm, 7, tsock, ended)
        self.assertEqual(may_still_open.call_count, 2)
        may_still_open.assert_called_with(7, vm)
        tsock.shutdown.assert_called_once_with(novncd_mod.socket.SHUT_RDWR)

    def test_a_token_of_a_serial_console_does_not_open_a_vnc_console(self):
        user = get_user_model().objects.create_user("vnc-owner", password="pw")
        compute = Compute.objects.create(name="novnc-type-compute", hostname="127.0.0.1", login="root", password="", type=1)
        instance = Instance.objects.create(compute=compute, name="novnc-type-vm", uuid="77777777-7777-7777-7777-777777777777")
        UserInstance.objects.create(instance=instance, user=user)
        self.assertEqual(tokens.authorize(tokens.sign(compute.id, instance.uuid, user.id, "vnc"), "vnc"), (instance, user))
        with self.assertRaises(PermissionError):
            tokens.authorize(tokens.sign(compute.id, instance.uuid, user.id, "pty"), "vnc")

    @patch("sys.argv", ["novncd"])
    @override_settings(DEBUG=False)
    def test_vnc_token_invalid_token_in_production(self):
        with self.assertRaises(PermissionError):
            tokens.authorize("invalid-raw-token", "vnc")

    def test_vnc_token_unauthorized_user(self):
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

        token = tokens.sign(compute.id, instance.uuid, unauthorized_user.id, "vnc")

        with self.assertRaises(PermissionError):
            tokens.authorize(token, "vnc")

    def test_vnc_token_rejects_signed_token_without_user(self):
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
            tokens.authorize(token, "vnc")

    def test_vnc_token_rejects_unsigned_token_even_under_test_runner(self):
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
            tokens.authorize(f"{compute.id}-{instance.uuid}", "vnc")

    def test_vnc_token_view_instances_user_is_not_enough(self):
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

        token = tokens.sign(compute.id, instance.uuid, viewer.id, "vnc")

        with self.assertRaises(PermissionError):
            tokens.authorize(token, "vnc")

    def test_vnc_token_inactive_user(self):
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

        token = tokens.sign(compute.id, instance.uuid, inactive_user.id, "vnc")

        with self.assertRaises(PermissionError):
            tokens.authorize(token, "vnc")

    @patch("sys.argv", ["novncd"])
    @override_settings(DEBUG=True)
    def test_vnc_token_debug_true_does_not_bypass(self):
        with self.assertRaises(PermissionError):
            tokens.authorize("invalid-token-in-debug", "vnc")

    @patch("sys.argv", ["novncd"])
    def test_vnc_token_expired_token(self):
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
            expired_token = tokens.sign(compute.id, instance.uuid, user.id, "vnc")

        with self.assertRaises(PermissionError):
            tokens.authorize(expired_token, "vnc")
