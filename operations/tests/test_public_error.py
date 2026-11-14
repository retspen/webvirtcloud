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

    def test_a_host_device_refusal_names_no_other_vm(self):
        from vrtManager.nodedevs import HostDevicesRefused
        from vrtManager.util import message

        refused = HostDevicesRefused("%(problems)s", problems=[message("%(device)s is given to %(vms)s",
                                                                       device="PCI device 0000:00:0a.0", vms="private-db-1")])
        self.assertNotIn("private-db-1", public_error_text(refused))
        self.assertIn("Host devices tab", public_error_text(refused))
