"""A protected VM: only a superuser turns its protection on or off; while on, the VM is not deleted nor
restored over (refusals in test_destroy and vmbackups.tests.test_restore_over)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from instances.models import Instance
from operations import claims
from operations.models import Claim
from instances.tests import test_pending_edits
from logs.models import Logs


class ProtectedTestCase(TestCase):
    setUp = test_pending_edits.PendingEditsTestCase.setUp
    page = test_pending_edits.PendingEditsTestCase.page  # the VM page with its host faked

    def test_only_a_superuser_turns_it_on_and_off(self):
        url = reverse("instances:set_protected", args=[self.instance.id])
        owner = get_user_model().objects.create_user("pr_owner", password="x", is_staff=True)
        UserInstance.objects.create(instance=self.instance, user=owner, is_change=True, is_delete=True)
        self.client.force_login(owner)
        self.assertEqual(self.client.post(url, {"protected": "True"}).status_code, 403)
        self.assertFalse(Instance.objects.get(pk=self.instance.pk).protected)

        self.client.force_login(get_user_model().objects.get(username="pe-admin"))
        self.client.post(url, {"protected": "True"})
        self.assertTrue(Instance.objects.get(pk=self.instance.pk).protected)
        self.client.post(url, {})
        self.assertFalse(Instance.objects.get(pk=self.instance.pk).protected)
        self.assertEqual([m.split(": ")[-1] for m in Logs.objects.filter(instance="pe-vm").order_by("pk").values_list("message", flat=True)],
                         ["protect", "unprotect"])

    def test_the_page_tells_it_and_offers_no_deletion(self):
        doc = self.page()
        (switch,) = doc.xpath("//input[@id='protected']")
        self.assertIsNone(switch.get("checked"))
        self.assertTrue(doc.xpath("//a[@href=$a]", a=reverse("instances:destroy", args=[self.instance.id])))
        Instance.objects.filter(pk=self.instance.pk).update(protected=True)
        doc = self.page()
        (switch,) = doc.xpath("//input[@id='protected']")
        self.assertIsNotNone(switch.get("checked"))
        self.assertFalse(doc.xpath("//a[@href=$a]", a=reverse("instances:destroy", args=[self.instance.id])))
        self.assertIn("This VM is protected", doc.text_content())

    def test_not_changed_while_a_job_holds_the_vm(self):
        # a deletion or a restore over it that runs would not stop
        claims.admit({claims.instance_key(self.instance.uuid): Claim.EXCLUSIVE}, holder="192.0.2.30:1:1")
        self.client.post(reverse("instances:set_protected", args=[self.instance.id]), {"protected": "True"})
        self.assertFalse(Instance.objects.get(pk=self.instance.pk).protected)

    def test_the_destroy_page_offers_no_form(self):
        Instance.objects.filter(pk=self.instance.pk).update(protected=True)
        page = self.client.get(reverse("instances:destroy", args=[self.instance.id]))
        self.assertContains(page, "This VM is protected")
        self.assertNotContains(page, 'id="delete_form"')
