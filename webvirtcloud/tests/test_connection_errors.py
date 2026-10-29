"""An error page for a host that cannot be reached shows the connection error
(host, address) only to administrators; errors of the VM operation itself
are shown to everyone, as they explain what to do."""

from unittest.mock import MagicMock

import libvirt
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from vrtManager.util import ConnectionFailed
from webvirtcloud.middleware import ExceptionMiddleware, error_text

HOST_DETAIL = "ssh: connect to host 10.0.0.9 port 22: No route to host"


def libvirt_error(domain, text, code=libvirt.VIR_ERR_SYSTEM_ERROR):
    err = libvirt.libvirtError.__new__(libvirt.libvirtError)
    Exception.__init__(err, text)
    err.err = (code, domain, text, 2, None, None, None, 0, 0)
    return err


class ConnectionErrorPageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("ce-owner", password="pw")
        self.admin = User.objects.create_superuser("ce-admin", "ce@example.com", "pw")
        self.viewer = User.objects.create_user("ce-viewer", password="pw")
        self.viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        self.viewer = User.objects.get(pk=self.viewer.pk)

    def handle(self, user, exception, path="/instances/1/poweron/", method="post", **headers):
        request = getattr(RequestFactory(), method)(path, **headers)
        SessionMiddleware(lambda r: None).process_request(request)
        request._messages = FallbackStorage(request)
        request.user = user
        response = ExceptionMiddleware(MagicMock()).process_exception(request, exception)
        return response, [str(m) for m in get_messages(request)]

    def test_owner_does_not_see_connection_details(self):
        for error in (
            ConnectionFailed(f"Connection Failed: Cannot recv data: {HOST_DETAIL}"),
            libvirt_error(libvirt.VIR_FROM_RPC, f"Cannot recv data: {HOST_DETAIL}"),
        ):
            with self.subTest(error=str(error)):
                response, messages = self.handle(self.owner, error)
                self.assertNotIn("10.0.0.9", " ".join(messages))
                self.assertTrue(any("cannot be reached" in m for m in messages), messages)

    def test_a_refused_form_goes_back_to_its_page_with_the_error(self):
        error = libvirt_error(libvirt.VIR_FROM_QEMU, "Requested operation is not valid: domain is not running",
                              libvirt.VIR_ERR_OPERATION_INVALID)
        response, messages = self.handle(self.admin, error, HTTP_REFERER="http://testserver/instances/1/#network")
        self.assertEqual((response.status_code, response["Location"]), (302, "http://testserver/instances/1/"))
        self.assertTrue(any("domain is not running" in m for m in messages), messages)
        for referer in ({}, {"HTTP_REFERER": "https://evil.example/"}):
            with self.subTest(referer=referer):
                response, _ = self.handle(self.admin, error, **referer)
                self.assertEqual(response["Location"], "/")

    def test_a_page_that_cannot_be_shown_is_the_error_page(self):
        response, messages = self.handle(self.admin, libvirt_error(libvirt.VIR_FROM_RPC, HOST_DETAIL),
                                         path="/instances/1/", method="get")
        self.assertEqual(response.status_code, 500)
        self.assertIn(b"Could not load data from the host", response.content)
        self.assertIn(HOST_DETAIL.encode(), response.content)
        self.assertTrue(messages)

    def test_administrators_see_connection_details(self):
        for user in (self.admin, self.viewer):
            with self.subTest(user=user.username):
                _, messages = self.handle(user, libvirt_error(libvirt.VIR_FROM_RPC, f"Cannot recv data: {HOST_DETAIL}"))
                self.assertIn("10.0.0.9", " ".join(messages))

    def test_operation_errors_are_shown_to_everyone(self):
        for error, text in (
            (libvirt_error(libvirt.VIR_FROM_QEMU, "Requested operation is not valid: domain is not running",
                           libvirt.VIR_ERR_OPERATION_INVALID), "domain is not running"),
            # a reachable daemon without the procedure answers from the RPC layer
            (libvirt_error(libvirt.VIR_FROM_RPC, "this function is not supported by the connection driver: virDomainFoo",
                           libvirt.VIR_ERR_NO_SUPPORT), "not supported"),
        ):
            with self.subTest(text=text):
                _, messages = self.handle(self.owner, error)
                self.assertIn(text, " ".join(messages))

    def test_api_answers_the_same_way(self):
        response, _ = self.handle(self.owner, ConnectionFailed(f"Connection Failed: {HOST_DETAIL}"), path="/api/v1/instances/1/")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"10.0.0.9", response.content)
        response, _ = self.handle(self.admin, ConnectionFailed(f"Connection Failed: {HOST_DETAIL}"), path="/api/v1/instances/1/")
        self.assertIn(b"10.0.0.9", response.content)

    def test_views_that_report_the_error_themselves(self):
        request = RequestFactory().post("/")
        request.user = self.owner
        self.assertNotIn("10.0.0.9", error_text(request, libvirt_error(libvirt.VIR_FROM_RPC, HOST_DETAIL)))
        self.assertEqual(error_text(request, ValueError("bad name")), "bad name")  # clone also reports these
