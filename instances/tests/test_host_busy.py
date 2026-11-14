"""A host whose web requests in this process all still wait for it is busy,
not unreachable: users are told to try again."""

from unittest.mock import PropertyMock, patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from operations.utils import public_error_text
from vrtManager import util

BUSY = "The host of this virtual machine is busy with other requests right now: try again in a moment."


def busy(host="192.0.2.1"):
    return util.HostBusy("Connection Failed: %(host)s does not answer: %(requests)s requests still wait for it",
                         host=host, requests=2)


class HostBusyTests(TestCase):
    def test_a_refused_request_tells_users_the_host_is_busy(self):
        self.assertEqual(public_error_text(busy()), BUSY)

    def test_the_vm_page_of_a_busy_host_says_it_is_busy(self):
        compute = Compute.objects.create(name="c", hostname="192.0.2.1", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="vm", uuid="11111111-1111-1111-1111-111111111111")
        owner = get_user_model().objects.create_user("owner", password="pw")
        UserInstance.objects.create(user=owner, instance=vm)
        self.client.force_login(owner)
        with patch.object(Compute, "connection", new_callable=PropertyMock, return_value=busy()):
            response = self.client.get(reverse("instances:instance", args=[vm.pk]))
        self.assertRedirects(response, reverse("instances:index"), fetch_redirect_response=False)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         [BUSY + " Jobs on it can be followed under Jobs in the menu."])
