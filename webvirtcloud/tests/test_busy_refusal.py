"""A request refused because its resource is held answers at once: the API
with 409 and the job holding it, a page with the reason on the form it came
from. Only the job's owner and superusers see who started it."""

import json
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from operations import claims
from operations.models import Operation
from operations.utils import busy_message
from webvirtcloud.middleware import ExceptionMiddleware


class BusyRefusalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("busy-owner", password="pw")
        self.other = User.objects.create_user("busy-other", password="pw")
        self.job = Operation.objects.create(kind="test.noop", user=self.owner, username="busy-owner",
                                            submission_key="k", resource="instance:u1", resource_label="c/vm")

    def handle(self, path, busy):
        request = RequestFactory().post(path)
        SessionMiddleware(lambda r: None).process_request(request)
        request._messages = FallbackStorage(request)
        request.user = self.owner
        response = ExceptionMiddleware(MagicMock()).process_exception(request, busy)
        return response, [str(m) for m in get_messages(request)]

    def test_the_api_answers_409_with_the_job(self):
        response, _ = self.handle("/api/v1/computes/1/instances/", claims.Busy("compute:1", self.job))
        self.assertEqual(response.status_code, 409)
        body = json.loads(response.content)
        self.assertIn("busy-owner", body["detail"])
        self.assertEqual(body["operation"]["id"], str(self.job.id))

    def test_a_page_is_sent_back_to_its_form_with_the_reason(self):
        response, messages = self.handle("/computes/1/create/", claims.Busy("compute:1"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/computes/1/create/")
        self.assertTrue(any("short operation" in m for m in messages), messages)

    def test_only_the_owner_learns_who_started_the_job(self):
        busy = claims.Busy("instance:u1", self.job)
        self.assertIn("busy-owner", busy_message(busy, self.owner))
        self.assertNotIn("busy-owner", busy_message(busy, self.other))
