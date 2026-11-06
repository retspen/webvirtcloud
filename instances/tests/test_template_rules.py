"""
A template is not started (power on or power cycle, web or API) and is
changed or deleted only by superusers and staff owners.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance
from operations.models import Operation


class TemplateRulesTestCase(TestCase):
    def setUp(self):
        compute = Compute.objects.create(name="tpl-c", hostname="192.0.2.5", login="root", password="", type=1)
        self.template = Instance.objects.create(
            compute=compute, name="tpl-vm", uuid="ffffffff-0000-1111-2222-333333333333", is_template=True
        )
        self.owner = get_user_model().objects.create_user("tpl_owner", password="x")
        UserInstance.objects.create(instance=self.template, user=self.owner, is_delete=True)
        self.staff = get_user_model().objects.create_user("tpl_staff", password="x", is_staff=True)
        UserInstance.objects.create(instance=self.template, user=self.staff, is_delete=True)

    def test_power_cycle_does_not_start_a_template(self):
        api = APIClient()
        api.force_login(self.owner)
        self.client.force_login(self.owner)
        for post in (
            lambda: self.client.post(reverse("instances:powercycle", args=[self.template.id])),
            lambda: api.post(reverse("compute-instance-powercycle", args=[self.template.compute_id, self.template.id])),
        ):
            with patch("instances.models.wvmInstance") as wvm:
                post()
            self.assertFalse(wvm.return_value.start.called)
            self.assertFalse(wvm.return_value.force_shutdown.called)

    def test_only_staff_owners_delete_a_template(self):
        self.client.force_login(self.owner)
        with patch("instances.models.wvmInstance") as wvm:
            response = self.client.post(reverse("instances:destroy", args=[self.template.id]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(wvm.return_value.delete.called)

        self.client.force_login(self.staff)
        with patch("instances.models.wvmInstance"):
            self.client.post(reverse("instances:destroy", args=[self.template.id]), {"submission_key": "key-tpldel01"})
        self.assertTrue(Operation.objects.filter(kind="instance.delete").exists())  # queued

    def test_the_destroy_confirmation_page_offers_the_form_to_who_may_delete(self):
        url = reverse("instances:destroy", args=[self.template.id])
        superuser = get_user_model().objects.create_superuser("tpl_root", "r@example.com", "x")
        for user, status, form in ((superuser, 200, True), (self.staff, 200, True), (self.owner, 403, False)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                with patch("instances.models.wvmInstance") as wvm:
                    wvm.return_value.get_status.return_value = 5
                    response = self.client.get(url)
                self.assertEqual(response.status_code, status)
                self.assertEqual('id="delete_form"' in response.content.decode(), form)
