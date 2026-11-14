"""The error pages say what happened and what to do, in the panel's layout."""

from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import Client, RequestFactory, TestCase
from django.views.defaults import page_not_found, server_error


class ErrorPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ep-user", password="pw")
        self.client.force_login(self.user)

    def test_a_bad_request(self):
        response = self.client.get("/", HTTP_HOST="unknown.example")
        self.assertContains(response, "Bad request", status_code=400)
        self.assertContains(response, "ALLOWED_HOSTS", status_code=400)

    def test_a_page_the_user_may_not_open(self):
        response = self.client.get("/computes/")
        self.assertContains(response, "Access denied", status_code=403)
        self.assertContains(response, "Ask an administrator", status_code=403)

    def test_a_form_that_fails_its_security_check(self):
        response = Client(enforce_csrf_checks=True).post("/accounts/login/", {"username": "ep-user", "password": "pw"})
        self.assertContains(response, "Form could not be submitted", status_code=403)
        self.assertContains(response, "reload the page and submit the form again", status_code=403)

    def test_a_page_that_is_not_there_names_its_path(self):
        response = self.client.get("/no/such/page/")
        self.assertContains(response, "Page not found", status_code=404)
        self.assertContains(response, "<code>/no/such/page/</code>", status_code=404)

    def test_the_reason_of_a_not_found_is_not_shown(self):
        response = page_not_found(RequestFactory().get("/datasource/"), Http404("libvirt detail of the host"))
        self.assertNotIn(b"libvirt detail", response.content)

    def test_a_server_error_renders_without_a_request_context(self):
        response = server_error(RequestFactory().get("/"))
        self.assertContains(response, "Server error", status_code=500)
        self.assertContains(response, "tell an administrator the time", status_code=500)
