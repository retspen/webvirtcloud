"""
Only superusers and staff may mark or unmark a VM as a template, on its own
form: the title and description form leaves the flag alone.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance
from logs.models import Logs


class TemplateFlagTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="tpl_super", email="tpl_super@example.com", password="x"
        )
        self.owner = User.objects.create_user(username="tpl_owner", password="x")
        self.staff_owner = User.objects.create_user(
            username="tpl_staff_owner", password="x", is_staff=True
        )
        self.compute = Compute.objects.create(
            name="tpl-compute", hostname="127.0.0.1:1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="tpl-vm",
            uuid="dddddddd-eeee-ffff-0000-111111111111",
        )
        for user in (self.owner, self.staff_owner):
            UserInstance.objects.create(instance=self.instance, user=user, is_change=True)

    def _post(self, user, action, data, status=302):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 5
            # unmarking a template checks the owner's quota with the VM's size
            wvm.return_value.get_vcpu.return_value = 1
            wvm.return_value.get_memory.return_value = 1024
            wvm.return_value.get_disk_devices.return_value = []
            res = self.client.post(reverse(f"instances:{action}", args=[self.instance.id]), data)
        self.assertEqual(res.status_code, status)
        self.instance.refresh_from_db()

    def _make_template(self):
        self.instance.is_template = True
        self.instance.save(update_fields=["is_template"])

    def test_owner_cannot_mark_vm_as_template(self):
        self._post(self.owner, "set_template", {"is_template": "True"}, status=403)
        self.assertFalse(self.instance.is_template)

    def test_owner_cannot_change_a_template(self):
        # a template is changed only by superusers and staff owners
        self._make_template()
        self._post(self.owner, "change_options", {"title": "new title", "description": ""}, status=403)
        self.assertTrue(self.instance.is_template)

    def test_staff_owner_can_mark_and_unmark_template(self):
        self._post(self.staff_owner, "set_template", {"is_template": "True"})
        self.assertTrue(self.instance.is_template)
        # an unchecked switch is not submitted: "not a template"
        self._post(self.staff_owner, "set_template", {})
        self.assertFalse(self.instance.is_template)
        self.assertEqual(list(Logs.objects.filter(message__startswith="VM").order_by("id").values_list("message", "success")),
                         [("VM tpl-vm: mark as template", True), ("VM tpl-vm: unmark as template", True)])

    def test_superuser_can_unmark_template(self):
        self._make_template()
        self._post(self.superuser, "set_template", {})
        self.assertFalse(self.instance.is_template)

    def test_the_title_form_leaves_the_template_alone(self):
        self._make_template()
        self._post(self.superuser, "change_options", {"title": "t", "description": ""})
        self.assertTrue(self.instance.is_template)
