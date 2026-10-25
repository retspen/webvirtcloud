"""API tokens: a user makes them on the profile page, in a session that
passed the login (and its OTP), and scripts use them on the REST API."""

import re
from datetime import timedelta
from unittest.mock import patch

from accounts.models import ApiToken
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from logs.models import Logs
from lxml import html


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
    def test_a_token_shows_when_it_was_last_used(self):
        token = self.make()
        self.assertIsNone(ApiToken.objects.get().last_used)
        self.api(token)
        first = ApiToken.objects.get().last_used
        self.assertAlmostEqual(first, timezone.now(), delta=timedelta(seconds=5))
        # within a minute a request writes nothing
        self.api(token)
        self.assertEqual(ApiToken.objects.get().last_used, first)
        later = timezone.now() + timedelta(minutes=2)
        with patch("accounts.auth.timezone.now", return_value=later):
            self.api(token)
        self.assertEqual(ApiToken.objects.get().last_used, later)
        self.client.force_login(self.user)
        self.assertIn("Last used", self.client.get(reverse("accounts:profile")).content.decode())

    def test_a_user_has_at_most_ten_tokens(self):
        for number in range(10):
            self.make(name=f"t{number}")
        response = self.client.post(reverse("accounts:api_token_create"), {"name": "one more", "days": "30"})
        self.assertEqual(ApiToken.objects.filter(user=self.user).count(), 10)
        self.assertNotRegex(response.content.decode(), r"wvc_[0-9a-f]{64}")
        self.assertIn("at most 10", response.content.decode())

    def test_expired_tokens_do_not_count_toward_the_limit(self):
        for number in range(10):
            self.make(name=f"t{number}")
        ApiToken.objects.filter(name="t0").update(expiry=timezone.now() - timedelta(days=1))
        self.make(name="new")
        self.assertEqual(sorted(ApiToken.objects.values_list("name", flat=True))[:2], ["new", "t1"])


class AdminApiTokenTests(TestCase):
    """A superuser sees a user's tokens on the user's page and deletes one
    that may have leaked."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("tok-user", password="pw")
        self.admin = get_user_model().objects.create_superuser("tok-admin", "admin@example.com", "pw")
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:api_token_create"), {"name": "ansible", "days": "90"})
        self.token = re.search(r"wvc_[0-9a-f]{64}", response.content.decode()).group(0)
        self.stored = ApiToken.objects.get(user=self.user)

    def delete_url(self, user):
        return reverse("accounts:account_api_token_delete", args=[user.id, self.stored.token_key])

    def test_the_users_page_lists_the_tokens_without_them(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("accounts:account", args=[self.user.id])).content.decode()
        self.assertIn("ansible", page)
        self.assertIn(self.stored.token_key, page)
        self.assertIn(self.delete_url(self.user), page)
        self.assertNotIn(self.token, page)

    def test_a_superuser_deletes_a_users_token(self):
        self.client.force_login(self.admin)
        # the confirmation names whose token it is
        self.assertIn("API token ansible of tok-user", self.client.get(self.delete_url(self.user)).content.decode())
        self.assertRedirects(self.client.post(self.delete_url(self.user)),
                             reverse("accounts:account", args=[self.user.id]) + "#apitokens",
                             fetch_redirect_response=False)
        self.assertFalse(ApiToken.objects.exists())
        self.assertEqual(Logs.objects.order_by("id").values_list("message", "user").last(),
                         ("API token ansible of tok-user: delete", "tok-admin"))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("instance-list"), HTTP_AUTHORIZATION=f"Token {self.token}").status_code, 401)

    def test_only_a_superuser_deletes_another_users_token(self):
        other = get_user_model().objects.create_user("tok-other", password="pw")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.delete_url(self.user)).status_code, 403)
        # nor through the owner's own address: it names the caller's tokens only
        self.assertEqual(self.client.post(reverse("accounts:api_token_delete", args=[self.stored.token_key])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.delete_url(other)).status_code, 404)
        self.assertTrue(ApiToken.objects.exists())

    def test_the_user_list_counts_each_users_live_tokens(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:api_token_create"), {"name": "old", "days": "30"})
        ApiToken.objects.filter(name="old").update(expiry=timezone.now() - timedelta(days=1))
        self.client.force_login(self.admin)
        page = html.fromstring(self.client.get(reverse("admin:user_list")).content)
        headers = [th.text_content().strip() for th in page.xpath("//thead//th")]
        column = headers.index("API tokens")
        cells = {row.xpath("td")[0].text_content().strip(): row.xpath("td")[column] for row in page.xpath("//tbody/tr")}
        # the expired one is not counted; the count opens the user's tokens
        self.assertEqual(cells["tok-user"].text_content().strip(), "1")
        self.assertEqual(cells["tok-user"].xpath(".//a/@href"),
                         [reverse("accounts:account", args=[self.user.id]) + "#apitokens"])
        self.assertEqual(cells["tok-admin"].text_content().strip(), "")
