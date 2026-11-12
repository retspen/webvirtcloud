"""An option the page's form never sends (a hand-made request) is refused
with a message, not a server error; the API answers it with a 400."""

from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from operations.models import Operation


class BadOptionTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("opts", "opts@example.com", "pw"))
        compute = Compute.objects.create(name="opts-compute", hostname="localhost", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="opts-vm", uuid="11111111-2222-3333-4444-555555555556")
        self.proxy = MagicMock(**{"get_status.return_value": 5})
        patch("instances.models.wvmInstance", return_value=self.proxy).start()
        self.addCleanup(patch.stopall)

    def post(self, name, data):
        response = self.client.post(reverse(f"instances:{name}", args=[self.vm.pk]), data)
        return response, [str(m) for m in get_messages(response.wsgi_request)]

    def test_power_on_is_refused_with_a_message(self):
        response, messages = self.post("poweron", {"fresh": "garbage"})
        self.assertRedirects(response, reverse("instances:instance", args=[self.vm.pk]), fetch_redirect_response=False)
        self.assertEqual(messages, ["Invalid options: fresh"])
        self.proxy.start.assert_not_called()

    def test_delete_is_refused_with_a_message(self):
        response, messages = self.post("destroy", {"delete_disk": "garbage", "submission_key": "key-opts0001"})
        self.assertRedirects(response, reverse("instances:destroy", args=[self.vm.pk]), fetch_redirect_response=False)
        self.assertEqual(messages, ["Invalid options: delete_disk"])
        self.assertFalse(Operation.objects.exists())

    def test_the_api_answers_400(self):
        response = self.client.post(f"/api/v1/computes/{self.vm.compute_id}/instances/{self.vm.pk}/poweron/", {"fresh": "garbage"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.proxy.start.assert_not_called()
