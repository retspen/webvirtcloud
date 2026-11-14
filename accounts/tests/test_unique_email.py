"""An email address belongs to one user: "Lost OTP?" mails only an exact,
single match, so a second user with the same address would switch it off for both."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.forms import ProfileForm
from admin.forms import UserForm


class UniqueEmailTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw")
        self.bob = User.objects.create_user("bob", "", "pw")

    def test_the_profile_refuses_another_users_address(self):
        self.client.force_login(self.bob)
        response = self.client.post(reverse("accounts:profile"), {"email": "Alice@Example.com"})
        self.assertContains(response, "Another user has this email address")
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.email, "")

    def test_the_admin_form_refuses_another_users_address(self):
        form = UserForm({"username": "bob", "email": "alice@example.com", "is_active": "on"}, instance=self.bob)
        self.assertEqual(form.errors["email"], ["Another user has this email address"])

    def test_own_address_and_no_address_are_kept(self):
        User.objects.create_user("carol", "", "pw")
        self.assertTrue(ProfileForm({"email": ""}, instance=self.bob).is_valid())
        self.assertTrue(ProfileForm({"email": "alice@example.com"}, instance=self.alice).is_valid())
