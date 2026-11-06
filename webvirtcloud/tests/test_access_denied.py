"""A 401 or 403 answered to a signed-in user or to a request with an API
token leaves a Logs row; an anonymous one does not."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from logs.models import Logs


class AccessDeniedTests(TestCase):
    def test_a_page_refused_to_a_signed_in_user_is_logged(self):
        self.client.force_login(get_user_model().objects.create_user("plain"))
        response = self.client.get(reverse("admin:user_list"), HTTP_X_REAL_IP="192.0.2.7")
        self.assertEqual(response.status_code, 403)
        row = Logs.objects.get(message__startswith="Access denied")
        self.assertEqual((row.user, row.success, row.ip), ("plain", False, "192.0.2.7"))
        self.assertEqual(row.message, "Access denied (403): GET /admin/users/")

    def test_a_refused_api_token_is_logged(self):
        response = self.client.get(reverse("instance-list"), HTTP_AUTHORIZATION="Token wvc_" + "0" * 64)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Logs.objects.get(message__startswith="Access denied").message, "Access denied (401): GET /api/v1/instances/")

    def test_an_anonymous_refusal_is_not_logged(self):
        self.assertEqual(self.client.get(reverse("instance-list")).status_code, 401)
        self.assertFalse(Logs.objects.filter(message__startswith="Access denied").exists())
