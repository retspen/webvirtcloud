"""The app log is bounded (rotates) and written to a deterministic absolute
path, not the process working directory."""

import io
import logging
import os

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from webvirtcloud.log_context import RequestFilter
from webvirtcloud.middleware import RequestIdMiddleware


class LoggingConfigTestCase(TestCase):
    def test_default_handler_rotates(self):
        handler = settings.LOGGING["handlers"]["default"]
        self.assertEqual(handler["class"], "logging.handlers.RotatingFileHandler")
        self.assertGreater(handler["maxBytes"], 0)
        self.assertGreater(handler["backupCount"], 0)

    def test_log_path_is_absolute_and_not_cwd(self):
        handler = settings.LOGGING["handlers"]["default"]
        self.assertTrue(os.path.isabs(handler["filename"]), handler["filename"])

    def test_missing_log_directory_is_created_on_settings_import(self):
        # A clean checkout / CI / Docker build may not have the log's parent dir;
        # importing settings (logging config) must create it, not crash.
        import subprocess
        import sys
        import tempfile

        tmp = tempfile.mkdtemp()
        log = os.path.join(tmp, "nested", "wvc.log")
        env = {
            **os.environ,
            "WEBVIRTCLOUD_LOG_FILE": log,
            "DJANGO_SETTINGS_MODULE": "webvirtcloud.settings",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isdir(os.path.dirname(log)), log)


class RequestIdTestCase(TestCase):
    def test_a_line_of_a_request_names_the_request_user_and_address(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RequestFilter())
        handler.setFormatter(logging.Formatter(settings.LOGGING["formatters"]["standard"]["format"]))
        logger = logging.getLogger("webvirtcloud.tests.request")
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        def view(request):
            logger.warning("refused")
            return HttpResponse()

        # from nginx: its request ID, the client in X-Real-IP
        request = RequestFactory().get("/", HTTP_X_REQUEST_ID="0123456789abcdef" * 2, HTTP_X_REAL_IP="192.0.2.7")
        request.user = User.objects.create_user("alice")
        response = RequestIdMiddleware(view)(request)

        self.assertEqual(response["X-Request-ID"], "0123456789abcdef" * 2)
        self.assertIn(f"{'0123456789abcdef' * 2} alice 192.0.2.7: refused", stream.getvalue())

    def test_an_id_sent_by_a_client_cannot_write_into_the_log(self):
        response = self.client.get("/accounts/login/", HTTP_X_REQUEST_ID="x\n[forged] line")
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")


class NotFoundTestCase(TestCase):
    def test_a_404_is_not_logged_and_a_403_is(self):
        self.client.force_login(User.objects.create_user("plain"))
        with self.assertLogs("django.request", "WARNING") as logs:
            self.client.get("/no-such-page/")
            self.client.get("/admin/users/")
            logging.getLogger("django.request").warning("end")  # assertLogs needs one line
        self.assertEqual([line.split(":")[0] for line in logs.output], ["WARNING", "WARNING"])
        self.assertIn("Forbidden", logs.output[0])
