"""A job's checks in the worker refuse with Django's exceptions, which carry
no text: the job's error says why instead of being empty."""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import SimpleTestCase
from operations.utils import public_error_text


class PublicErrorTests(SimpleTestCase):
    def test_a_refusal_says_why(self):
        self.assertEqual(public_error_text(PermissionDenied()), "You may no longer do this.")
        self.assertEqual(public_error_text(Http404("No Instance matches the given query.")),
                         "The virtual machine is no longer in the panel.")
