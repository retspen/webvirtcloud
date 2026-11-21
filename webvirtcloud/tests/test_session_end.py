"""A session that ends while a page is open: its scripts are told so (401), and a form
sent then goes back to its page after the sign-in, said not done, not to a 405."""
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from lxml import html

from computes.models import Compute
from instances.models import Instance


class SessionEndTests(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="se-host", hostname="192.0.2.11", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="se-vm", uuid="00000000-0000-4000-8000-0000000000dd")
        self.page = reverse("instances:instance", args=[self.vm.pk])

    def test_a_script_asking_is_answered_401(self):
        response = self.client.get(reverse("instances:states"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 401)

    def test_a_page_asked_signs_in_and_comes_back(self):
        response = self.client.get(self.page)
        self.assertRedirects(response, reverse("accounts:login") + f"?next={self.page}", fetch_redirect_response=False)

    def test_a_form_sent_comes_back_to_its_page_and_says_it_was_not_done(self):
        response = self.client.post(reverse("instances:poweron", args=[self.vm.pk]),
                                    HTTP_REFERER=f"http://testserver{self.page}?x=1#power")
        self.assertRedirects(response, reverse("accounts:login") + "?next=" + self.page + "%3Fx%3D1",
                             fetch_redirect_response=False)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ["You were signed out, so it was not done: sign in and do it again."])
        # a Referer from elsewhere: the home page
        response = self.client.post(reverse("instances:poweron", args=[self.vm.pk]), HTTP_REFERER="https://example.com/x")
        self.assertRedirects(response, reverse("accounts:login") + "?next=/", fetch_redirect_response=False)

    def test_a_form_shown_again_at_its_own_address_goes_home(self):
        # an API token form with errors answers at the create address, which takes POST only
        create = reverse("accounts:api_token_create")
        response = self.client.post(create, HTTP_REFERER=f"http://testserver{create}")
        self.assertRedirects(response, reverse("accounts:login") + "?next=/", fetch_redirect_response=False)

    def test_an_options_request_is_not_said_lost(self):
        response = self.client.options(self.page)
        self.assertEqual(get_messages(response.wsgi_request)._queued_messages, [])

    def test_a_stale_token_after_the_end_goes_to_sign_in(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("instances:poweron", args=[self.vm.pk]), HTTP_REFERER=f"http://testserver{self.page}")
        self.assertRedirects(response, reverse("accounts:login") + f"?next={self.page}", fetch_redirect_response=False)
        # the sign-in form itself: Django's 403, as before
        self.assertEqual(client.post(reverse("accounts:login"), {"username": "x", "password": "y"}).status_code, 403)

    def test_a_signed_in_page_has_the_notice_hidden(self):
        self.client.force_login(get_user_model().objects.create_superuser("se-admin", "se@example.com", "pw"))
        (notice,) = html.fromstring(self.client.get(reverse("instances:index")).content).xpath("//*[@id='session-ended']")
        self.assertIsNotNone(notice.get("hidden"))
        self.assertIn("next=/instances/", notice.get("data-href"))
