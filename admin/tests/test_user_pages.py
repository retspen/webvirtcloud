"""The Users pages: an administrator cannot lock their own account out, the
user form says what its fields mean, and a password set by an administrator
can be one the user must change."""

from accounts.models import UserAttributes
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from lxml import html


class UserPagesTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("up-admin", "up@example.com", "pw")
        self.alice = User.objects.create_user("up-alice", password="Alice-pw-123")
        UserAttributes.objects.get_or_create(user=self.alice)
        self.client.force_login(self.admin)

    def messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    def form_data(self, user, **changes):
        data = {"username": user.username, "is_active": "on", "is_superuser": "on" if user.is_superuser else "",
                "max_instances": "2", "max_cpus": "2", "max_memory": "2048", "max_disk_size": "20", **changes}
        return {key: value for key, value in data.items() if value != ""}

    def test_an_administrator_cannot_block_delete_or_demote_themselves(self):
        own = self.admin.pk
        for response in (self.client.post(reverse("admin:user_block", args=[own])),
                         self.client.post(reverse("admin:user_delete", args=[own]))):
            self.assertIn("You cannot block, delete or demote your own account", self.messages(response))
        for change in ({"is_superuser": ""}, {"is_active": ""}):
            response = self.client.post(reverse("admin:user_update", args=[own]), self.form_data(self.admin, **change))
            self.assertContains(response, "You cannot block, delete or demote your own account")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active and self.admin.is_superuser)
        # another user's account is theirs to change
        self.client.post(reverse("admin:user_block", args=[self.alice.pk]))
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_active)

    def test_the_form_tells_the_password_state_and_links_its_page(self):
        page = html.fromstring(self.client.get(reverse("admin:user_update", args=[self.alice.pk])).content)
        text = " ".join(page.text_content().split())
        self.assertIn("Password: Set Change password", text)
        self.assertNotIn("No password set", text)
        self.assertEqual(page.xpath("//a[normalize-space()='Change password']/@href"),
                         [reverse("admin:user_update_password", args=[self.alice.pk])])
        self.assertEqual(page.xpath("//a[@href='../password/']"), [])

    def test_staff_and_quotas_say_what_they_mean(self):
        page = self.client.get(reverse("admin:user_update", args=[self.alice.pk])).content.decode()
        self.assertIn("Template editor", page)
        self.assertIn("May change and delete the template VMs given to them", page)
        self.assertNotIn("log into this admin site", page)
        self.assertIn("Max memory (MiB)", page)
        self.assertIn("Max disk size (GiB)", page)
        self.assertIn("-1 means no limit, 0 none allowed", page)

    def test_a_refused_choice_is_said_beside_its_field(self):
        url = reverse("admin:user_update", args=[self.alice.pk])
        response = self.client.post(url, {"username": "up-alice", "is_active": "on", "groups": "99999", "user_permissions": "99999",
                                          "max_instances": 1, "max_cpus": 1, "max_memory": 1, "max_disk_size": 1})
        page = html.fromstring(response.content)
        self.assertEqual(len(page.xpath("//fieldset//div[contains(@class, 'invalid-feedback')]")), 2)

    def test_the_folded_quota_says_what_it_allows(self):
        UserAttributes.objects.filter(user=self.alice).update(max_instances=-1, max_cpus=1, max_memory=2048, max_disk_size=-1)
        page = html.fromstring(self.client.get(reverse("admin:user_update", args=[self.alice.pk])).content)
        (summary,) = [s for s in page.xpath("//summary") if "Quota" in s.text_content()]
        self.assertEqual(" ".join(summary.text_content().split()), "Quota any number of VMs · 1 vCPU · 2048 MiB · any disk size")

    def test_a_missing_users_profile_is_not_found(self):
        self.assertEqual(self.client.get(reverse("accounts:account", args=[99999])).status_code, 404)

    def test_a_user_who_never_logged_in_says_never(self):
        page = html.fromstring(self.client.get(reverse("admin:user_list")).content)
        (row,) = page.xpath("//div[contains(@class, 'list-group-item')][.//a[normalize-space()='up-alice']]")
        self.assertIn("Last login: never", " ".join(row.text_content().split()))

    def test_the_search_finds_a_user_by_role_and_status(self):
        self.alice.is_active = False
        self.alice.save()
        page = html.fromstring(self.client.get(reverse("admin:user_list")).content)
        (row,) = page.xpath("//div[contains(@class, 'list-group-item')][.//a[normalize-space()='up-alice']]")
        self.assertIn("User Blocked", row.get("data-search"))

    def test_a_password_set_by_an_administrator_can_be_one_to_change(self):
        url = reverse("admin:user_update_password", args=[self.alice.pk])
        self.client.post(url, {"password1": "New-pw-4567x", "password2": "New-pw-4567x", "must_change_password": "on"})
        self.assertTrue(UserAttributes.objects.get(user=self.alice).must_change_password)
        # the user is sent to the change form until they choose their own
        self.alice.refresh_from_db()  # the new password's hash, or the session is not hers
        self.client.force_login(self.alice)
        self.assertRedirects(self.client.get(reverse("instances:index")), reverse("accounts:change_password"),
                             fetch_redirect_response=False)
        self.client.force_login(self.admin)
        self.client.post(url, {"password1": "New-pw-4567y", "password2": "New-pw-4567y"})
        self.assertFalse(UserAttributes.objects.get(user=self.alice).must_change_password)

    def test_a_user_without_a_password_cannot_be_made_to_change_it(self):
        # the change form asks for the old password: one they never had
        url = reverse("admin:user_update_password", args=[self.alice.pk])
        response = self.client.post(url, {"usable_password": "false", "must_change_password": "on"})
        self.assertContains(response, "A user without a password cannot be made to change it")
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.has_usable_password())

    def test_an_administrator_keeps_their_own_password(self):
        url = reverse("admin:user_update_password", args=[self.admin.pk])
        response = self.client.post(url, {"usable_password": "false"})
        self.assertContains(response, "You cannot block, delete or demote your own account")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.has_usable_password())

