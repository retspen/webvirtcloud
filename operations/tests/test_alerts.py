"""Alerts: a failed backup, a scheduled backup not taken, backups found missing and an uncertain job are
queued with the change they tell of and sent by mail and webhook; /healthz tells a monitor whether the
worker runs."""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from appsettings.models import AppSettings
from operations import alerts, jobs
from operations.models import Alert, Operation, WorkerLease
from operations.utils import say


def channels(emails="ops@example.com", webhook=""):
    AppSettings.objects.filter(key="ALERT_EMAILS").update(value=emails)
    AppSettings.objects.filter(key="ALERT_WEBHOOK").update(value=webhook)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AlertTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("al_admin", "al@example.com", "pw")

    def op(self, kind):
        return Operation.objects.create(kind=kind, user=self.user, username="al_admin", state=Operation.RUNNING,
                                        submission_key=f"key-{Operation.objects.count():012d}",
                                        resource="backup:x", resource_label="vm1 2026-11-19 03:00", params={}, intent={})

    def test_none_queued_while_no_channel_is_set(self):
        channels("", "")
        alerts.alert(say("Subject"), say("Text"))
        self.assertFalse(Alert.objects.exists())

    def test_a_failed_backup_and_an_uncertain_job_are_alerts_a_failed_other_job_is_not(self):
        channels()
        jobs.finish(self.op("backup.create"), jobs.Outcome(Operation.FAILED, error=say("Disk full")))
        jobs.finish(self.op("instance.migrate"), jobs.Outcome(Operation.FAILED, error=say("Refused")))
        jobs.finish(self.op("instance.clone"), jobs.Outcome(Operation.UNCERTAIN, error=say("Host gone")))
        jobs.finish(self.op("backup.create"), jobs.Outcome(Operation.SUCCEEDED))
        alerts.send()
        subjects = [m.subject for m in mail.outbox]
        self.assertEqual(subjects, ["WebVirtCloud: Job failed: Back up VM: vm1 2026-11-19 03:00",
                                    "WebVirtCloud: Job ended uncertain: Clone VM: vm1 2026-11-19 03:00"])
        Alert.objects.all().delete()
        mail.outbox.clear()
        with override_settings(LANGUAGE_CODE="tr"):  # in the panel's language, the kind's label too
            jobs.finish(self.op("backup.create"), jobs.Outcome(Operation.FAILED, error=say("Disk full")))
            alerts.send()
        self.assertEqual(mail.outbox[0].subject, "WebVirtCloud: İş başarısız: Sanal makineyi yedekle: vm1 2026-11-19 03:00")
        self.assertIn("Disk full", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["ops@example.com"])
        self.assertTrue(all(a.sent_at for a in Alert.objects.all()))

    def test_a_plain_text_error_or_a_failing_queue_never_stops_a_job_ending(self):
        channels()
        jobs.finish(self.op("instance.clone"), jobs.Outcome(Operation.UNCERTAIN, error=["plain words"]))
        op = self.op("backup.create")
        with patch("operations.alerts.Alert.objects.create", side_effect=RuntimeError("queue broke")):
            jobs.finish(op, jobs.Outcome(Operation.FAILED, error=say("Disk full")))
        op.refresh_from_db()
        self.assertEqual(op.state, Operation.FAILED)
        alerts.send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("plain words", mail.outbox[0].body)

    def test_the_webhook_gets_json_and_a_failing_channel_is_tried_again_alone(self):
        channels("ops@example.com", "https://hooks.example.com/x")
        alerts.alert(say("Subject"), say("Text"))
        with patch("operations.alerts._post", side_effect=OSError("refused")):
            alerts.send()
        notice = Alert.objects.get()
        self.assertEqual((notice.mailed, notice.posted, notice.sent_at, notice.tries), (True, False, None, 1))
        self.assertIn("webhook: refused", notice.error)
        with patch("operations.alerts._post", MagicMock()) as urlopen:
            alerts.send()
        self.assertEqual(len(mail.outbox), 1)  # not mailed twice
        url, body = urlopen.call_args.args
        self.assertEqual(url, "https://hooks.example.com/x")
        self.assertEqual(json.loads(body)["subject"], "Subject")
        self.assertTrue(Alert.objects.get().sent_at)

    def test_a_channel_down_is_tried_once_a_pass_and_notices_wait_without_channels(self):
        channels("", "https://hooks.example.com/x")
        for _ in range(3):
            alerts.alert(say("Subject"), say("Text"))
        with patch("operations.alerts._post", side_effect=OSError("timed out")) as urlopen:
            alerts.send()
        self.assertEqual(urlopen.call_count, 1)  # one timeout a pass, not one a notice
        self.assertEqual(sorted(Alert.objects.values_list("tries", flat=True)), [0, 0, 1])  # the others not tried
        alerts.alert(say("Newer"), say("Text"))
        with patch("operations.alerts._post") as urlopen:
            alerts.send()
        self.assertEqual(json.loads(urlopen.call_args_list[0].args[1])["subject"], "Subject")  # the least tried first
        self.assertEqual(Alert.objects.filter(sent_at__isnull=True).count(), 0)
        Alert.objects.update(sent_at=None, posted=False)
        channels("", "")
        alerts.send()
        self.assertFalse(Alert.objects.filter(sent_at__isnull=False).exists())

    def test_a_try_another_worker_claimed_is_not_sent_again(self):
        channels()
        alerts.alert(say("Subject"), say("Text"))
        real = Alert.objects.filter

        def taken_meanwhile(*args, **kwargs):
            if "tries" in kwargs:  # the claim: another worker's came first
                Alert.objects.update(tries=1)
            return real(*args, **kwargs)

        with patch.object(Alert.objects, "filter", side_effect=taken_meanwhile):
            alerts.send()
        self.assertEqual(mail.outbox, [])

    def test_a_redirect_is_no_delivery(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading

        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.end_headers()

            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=server.handle_request, daemon=True).start()
        self.addCleanup(server.server_close)
        with self.assertRaises(Exception):
            alerts._post(f"http://127.0.0.1:{server.server_port}/notify", b"{}")

    def test_a_notice_is_given_up_after_its_tries_and_old_ones_go(self):
        channels("", "https://hooks.example.com/x")
        alerts.alert(say("Subject"), say("Text"))
        with patch("operations.alerts._post", side_effect=OSError("refused")) as urlopen:
            for _ in range(alerts.TRIES + 2):
                alerts.send()
        self.assertEqual(urlopen.call_count, alerts.TRIES)
        Alert.objects.update(created_at=timezone.now() - alerts.KEPT - timedelta(minutes=1))
        alerts.send()
        self.assertFalse(Alert.objects.exists())

    def test_the_settings_page_refuses_a_bad_address_or_url(self):
        self.client.force_login(self.user)
        for key, value in (("ALERT_EMAILS", "ops@example.com, not-an-address"), ("ALERT_WEBHOOK", "ftp://x.example.com/")):
            with self.subTest(key=key):
                setting = AppSettings.objects.get(key=key)
                self.client.post(reverse("appsettings"), {key: value, f"was-{key}": setting.value})
                self.assertEqual(AppSettings.objects.get(key=key).value, "")
        self.client.post(reverse("appsettings"), {"ALERT_WEBHOOK": "https://u:secret@hooks.example.com/x", "was-ALERT_WEBHOOK": ""})
        self.assertEqual(AppSettings.objects.get(key="ALERT_WEBHOOK").value, "")
        self.client.post(reverse("appsettings"), {"ALERT_EMAILS": "a@example.com, b@example.com", "was-ALERT_EMAILS": ""})
        self.assertEqual(AppSettings.objects.get(key="ALERT_EMAILS").value, "a@example.com, b@example.com")
        url = "https://hooks.slack.example.com/services/T0000000/B0000000/" + "x" * 40
        self.client.post(reverse("appsettings"), {"ALERT_WEBHOOK": url, "was-ALERT_WEBHOOK": ""})
        self.assertEqual(AppSettings.objects.get(key="ALERT_WEBHOOK").value, url)
        from logs.models import Logs
        self.assertFalse(Logs.objects.filter(message__contains="x" * 40).exists())  # a secret of its own
        self.assertContains(self.client.get(reverse("appsettings")), 'maxlength="255"')


    def test_a_test_alert_goes_at_once_to_each_channel_saved(self):
        self.client.force_login(self.user)
        channels("", "")
        response = self.client.post(reverse("appsettings"), {"test_alert": "1"}, follow=True)
        self.assertContains(response, "Set an alert e-mail address or webhook and save it first")
        channels("ops@example.com", "https://hooks.example.com/x")
        with patch("operations.alerts._post", side_effect=OSError("refused")):
            response = self.client.post(reverse("appsettings"), {"test_alert": "1"}, follow=True)
        self.assertContains(response, "E-mail: the test alert was sent")
        self.assertContains(response, "Webhook: the test alert failed: refused")
        self.assertEqual(mail.outbox[0].subject, "WebVirtCloud: Test alert")
        self.assertFalse(Alert.objects.exists())  # not queued
        page = self.client.get(reverse("appsettings")).content.decode()
        self.assertLess(page.index("Save Alerts"), page.index('name="test_alert"'))  # Enter saves


class HealthzTests(TestCase):
    def test_without_a_login_it_tells_whether_the_worker_runs(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual((response.status_code, response.json()["worker"]), (503, False))
        WorkerLease.objects.create(holder="w", host="h", heartbeat_at=timezone.now())
        response = self.client.get(reverse("healthz"))
        self.assertEqual((response.status_code, response.json()["worker"], response.json()["database"]), (200, True, True))
        WorkerLease.objects.update(heartbeat_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.client.get(reverse("healthz")).status_code, 503)
        from django.db import InterfaceError
        with patch("operations.views.last_seen", side_effect=InterfaceError("connection already closed")):
            response = self.client.get(reverse("healthz"))
        self.assertEqual((response.status_code, response.json()["database"]), (503, False))
        self.assertIn("no-store", response["Cache-Control"])
