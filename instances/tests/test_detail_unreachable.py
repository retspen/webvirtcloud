"""The page of a VM whose host cannot be reached sends the user to the list
with a message, instead of the error page with libvirt's connection error."""

from unittest.mock import PropertyMock, patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import libvirtError

ERROR = "Connection Failed: ssh: connect to host 192.0.2.9 port 22: No route to host"


class DetailOfUnreachableHostTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="far-host", hostname="192.0.2.9", login="root", password="", type=2)
        self.vm = Instance.objects.create(compute=self.compute, name="far-vm", uuid="56565656-0000-0000-0000-000000000000")
        self.owner = get_user_model().objects.create_user("far-owner", password="pw")
        UserInstance.objects.create(user=self.owner, instance=self.vm)

    def get(self, user):
        self.client.force_login(user)
        with patch.object(Compute, "connection", new_callable=PropertyMock, return_value=libvirtError(ERROR)), \
                patch("instances.models.wvmInstance", side_effect=AssertionError("VM read on a down host")):
            response = self.client.get(reverse("instances:instance", args=[self.vm.id]))
        self.assertRedirects(response, reverse("instances:index"), fetch_redirect_response=False)
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_owner_is_told_without_host_details(self):
        messages = self.get(self.owner)
        self.assertEqual(len(messages), 1)
        self.assertIn("far-vm", messages[0])
        self.assertNotIn("far-host", messages[0])
        self.assertNotIn("192.0.2.9", messages[0])
        self.assertIn("Jobs", messages[0])

    def test_superuser_sees_the_host_and_its_error(self):
        admin = get_user_model().objects.create_superuser("far-admin", password="pw", email="far@example.com")
        messages = self.get(admin)
        self.assertEqual(len(messages), 1)
        self.assertIn("far-host", messages[0])
        self.assertIn(ERROR, messages[0])
