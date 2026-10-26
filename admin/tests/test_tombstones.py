"""Superusers list the ownership kept for VMs that vanished and can remove it."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from instances.models import InstanceTombstone

UUID = "00000000-0000-4000-8000-000000000001"


class TombstoneTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("ts-admin", "ts@example.com", "pw"))
        self.owner = User.objects.create_user("ts-owner", password="pw")
        self.tombstone = InstanceTombstone.objects.create(
            uuid=UUID,
            name="ts-vm",
            host="ts-host",
            owners=[
                {"user": self.owner.id, "is_change": True, "is_delete": False, "is_vnc": True},
                {"user": 999999, "is_change": False, "is_delete": False, "is_vnc": False},
            ],
        )

    @override_settings(INSTANCE_OWNERSHIP_RETENTION_DAYS=7)
    def test_the_list_shows_the_vm_its_owners_and_when_it_expires(self):
        removed = timezone.now() - timedelta(days=2)
        InstanceTombstone.objects.filter(pk=self.tombstone.pk).update(removed=removed)
        response = self.client.get(reverse("admin:tombstone_list"))
        self.assertEqual(response.status_code, 200)
        row = response.context["tombstones"][0]
        self.assertEqual(row.owner_names, ["ts-owner", "deleted user"])
        self.assertEqual(row.expires, removed + timedelta(days=7))
        self.assertContains(response, "ts-vm")
        self.assertContains(response, UUID)
        self.assertContains(response, "ts-owner")
        self.assertContains(response, "<td>ts-host</td>", html=True)
        self.assertContains(response, '<th scope="col">Host</th>', html=True)

    def test_only_superusers_see_or_remove_them(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("admin:tombstone_list")).status_code, 403)
        url = reverse("admin:tombstone_delete", args=[self.tombstone.pk])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(InstanceTombstone.objects.exists())

    def test_a_get_only_asks_for_confirmation(self):
        response = self.client.get(reverse("admin:tombstone_delete", args=[self.tombstone.pk]))
        self.assertContains(response, "ts-vm")
        self.assertTrue(InstanceTombstone.objects.exists())

    def test_a_post_removes_it(self):
        response = self.client.post(reverse("admin:tombstone_delete", args=[self.tombstone.pk]), follow=True)
        self.assertRedirects(response, reverse("admin:tombstone_list"))
        self.assertContains(response, "Removed VM ts-vm deleted")
        self.assertFalse(InstanceTombstone.objects.exists())
