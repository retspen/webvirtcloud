"""After saving a user, the edit page goes back to ?next= only on this site."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from admin.tests.edits import user_seen

LIMITS = {"role": "user", "max_instances": 1, "max_cpus": 1, "max_memory": 1, "max_disk_size": 4}


class UserUpdateNextTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("un-admin", "un@example.com", "pw"))
        self.user = User.objects.create_user("un-user", password="pw")

    def save(self, next_url):
        url = reverse("admin:user_update", args=[self.user.id]) + "?next=" + next_url
        return self.client.post(url, {"username": "un-user", "is_active": "on", "seen": user_seen(self.user), **LIMITS})

    def test_a_page_of_this_site(self):
        account = reverse("accounts:account", args=[self.user.id])
        self.assertRedirects(self.save(account), account, fetch_redirect_response=False)

    def test_another_site_is_not_followed(self):
        for next_url in ("https://evil.example/", "//evil.example/", "/\\evil.example/"):
            with self.subTest(next_url=next_url):
                self.assertRedirects(self.save(next_url), reverse("admin:user_list"), fetch_redirect_response=False)
