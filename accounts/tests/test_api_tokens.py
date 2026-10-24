"""API tokens: a user makes them on the profile page, in a session that
passed the login (and its OTP), and scripts use them on the REST API."""

import re
from datetime import timedelta

from accounts.models import ApiToken
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from logs.models import Logs


class ApiTokenTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("tok-user", password="pw")
        self.other = get_user_model().objects.create_user("tok-other", password="pw")

    def make(self, name="ansible", days="90"):
        """The token the creation page shows once."""
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:api_token_create"), {"name": name, "days": days})
        self.assertEqual(response.status_code, 200)
        return re.search(r"wvc_[0-9a-f]{64}", response.content.decode()).group(0)

    def api(self, token):
        self.client.logout()
        return self.client.get(reverse("instance-list"), HTTP_AUTHORIZATION=f"Token {token}")

    def test_a_token_opens_the_api_without_a_session(self):
        token = self.make()
        response = self.api(token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])  # the user's own VMs: none

    def test_a_token_is_kept_only_as_a_hash_and_shown_once(self):
        token = self.make(name="ci")
        (stored,) = ApiToken.objects.filter(user=self.user)
        self.assertEqual((stored.name, stored.token_key), ("ci", token[:15]))
        self.assertNotIn(token, stored.digest)
        page = self.client.get(reverse("accounts:profile")).content.decode()
        self.assertIn("ci", page)
        self.assertNotIn(token, page)

    def test_the_page_showing_the_token_is_not_cached(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:api_token_create"), {"name": "ci", "days": "30"})
        self.assertIn("no-store", response["Cache-Control"])

    def test_a_token_lasts_the_days_chosen_or_until_deleted(self):
        self.make(name="month", days="30")
        self.make(name="always", days="")
        expiry = dict(ApiToken.objects.values_list("name", "expiry"))
        self.assertAlmostEqual(expiry["month"], timezone.now() + timedelta(days=30), delta=timedelta(minutes=1))
        self.assertIsNone(expiry["always"])

    def test_an_expired_token_or_a_wrong_one_is_refused(self):
        token = self.make()
        ApiToken.objects.update(expiry=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.api(token).status_code, 401)
        self.assertEqual(self.api("wvc_" + "0" * 64).status_code, 401)

    def test_an_inactive_users_token_is_refused(self):
        token = self.make()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.api(token).status_code, 401)

    def test_a_deleted_token_stops_working_and_only_its_owner_deletes_it(self):
        token = self.make()
        stored = ApiToken.objects.get(user=self.user)
        url = reverse("accounts:api_token_delete", args=[stored.token_key])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.user)
        self.assertRedirects(self.client.post(url), reverse("accounts:profile") + "#apitokens",
                             fetch_redirect_response=False)
        self.assertEqual(self.api(token).status_code, 401)

    def test_making_and_deleting_a_token_is_logged_without_the_token(self):
        token = self.make(name="backup")
        stored = ApiToken.objects.get(user=self.user)
        self.client.post(reverse("accounts:api_token_delete", args=[stored.token_key]))
        rows = list(Logs.objects.order_by("id").values_list("message", "success"))
        self.assertEqual(rows[-2:], [("API token backup: add", True), ("API token backup: delete", True)])
        self.assertFalse(Logs.objects.filter(message__contains=token[4:20]).exists())

    def test_a_token_needs_a_name(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:api_token_create"), {"name": " ", "days": "30"})
        self.assertFalse(ApiToken.objects.exists())
        self.assertNotRegex(response.content.decode(), r"wvc_[0-9a-f]{64}")

    def test_knox_makes_no_table_of_its_own(self):
        # accounts.ApiToken replaces knox's AuthToken; a knox_authtoken table
        # would reference auth_user unseen, and PostgreSQL could not empty
        # auth_user between tests
        self.assertNotIn("knox_authtoken", connection.introspection.table_names())
