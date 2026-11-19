"""Superusers rename and delete the tags of VMs and hosts."""

from django.contrib.auth.models import User
from django.test import TestCase
from unittest.mock import patch

from django.urls import reverse
from django.utils import translation

from computes.models import Compute, Tag
from instances.models import Instance, InstanceTombstone
from logs.models import Logs


class TagAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("tg-admin", "tg@example.com", "pw"))
        self.prod = Tag.objects.create(name="prod")
        compute = Compute.objects.create(name="tg", hostname="192.0.2.7", login="u", password="p", type=1)
        compute.tags.add(self.prod)
        Instance.objects.create(compute=compute, name="vm", uuid="12345678-0000-0000-0000-00000000dd01").tags.add(self.prod)
        self.tombstone = InstanceTombstone.objects.create(uuid="12345678-0000-0000-0000-00000000dd02", name="gone",
                                                          tags=["prod", "db"])

    def messages(self):
        return list(Logs.objects.filter(message__startswith="Tag").order_by("id").values_list("message", flat=True))

    def test_the_list_counts_each_tag_s_vms_and_hosts(self):
        response = self.client.get(reverse("admin:tag_list"))
        self.assertEqual([(t.name, t.vm_count, t.host_count) for t in response.context["tags"]], [("prod", 1, 1)])
        self.assertContains(response, 'class="badge tag-badge')  # as small as on the other pages

    def test_a_rename_keeps_the_tag_on_its_vms_hosts_and_removed_vms(self):
        self.client.post(reverse("admin:tag_update", args=[self.prod.pk]), {"name": "Live"})
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.name, "live")
        self.assertEqual(self.prod.instances.count(), 1)
        self.tombstone.refresh_from_db()
        self.assertEqual(self.tombstone.tags, ["live", "db"])
        self.assertEqual(self.messages(), ["Tag prod: rename to live"])

    def test_a_name_taken_or_bad_is_refused(self):
        Tag.objects.create(name="db")
        for name in ("DB", "two words", "x" * 13):
            with self.subTest(name):
                response = self.client.post(reverse("admin:tag_update", args=[self.prod.pk]), {"name": name})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.name, "prod")

    def test_a_delete_takes_it_off_everything(self):
        self.assertContains(self.client.get(reverse("admin:tag_delete", args=[self.prod.pk])), "1 VM and 1 host")
        self.client.post(reverse("admin:tag_delete", args=[self.prod.pk]))
        self.assertFalse(Tag.objects.exists())
        self.assertFalse(Instance.objects.get(name="vm").tags.exists())
        self.assertEqual(self.messages(), ["Tag prod: delete"])

    def test_a_deleted_name_made_again_is_not_given_to_a_vm_that_returns(self):
        self.client.post(reverse("admin:tag_delete", args=[self.prod.pk]))
        self.tombstone.refresh_from_db()
        self.assertEqual(self.tombstone.tags, ["db"])

    def test_the_same_name_is_no_rename(self):
        self.client.post(reverse("admin:tag_update", args=[self.prod.pk]), {"name": "PROD"})
        self.assertEqual(self.messages(), [])

    def test_a_tag_a_backup_schedule_uses_is_kept(self):
        import datetime
        from vmbackups.models import BackupPolicy, BackupTarget
        BackupPolicy.objects.create(name="nightly", target=BackupTarget.objects.create(name="nfs"), tag=self.prod,
                                    time=datetime.time(2), keep=3)
        # the confirm page is not shown, and a delete sent anyway (the schedule saved since) is refused
        self.assertContains(self.client.get(reverse("admin:tag_delete", args=[self.prod.pk]), follow=True),
                            "The backup schedule nightly backs up its VMs")
        response = self.client.post(reverse("admin:tag_delete", args=[self.prod.pk]), follow=True)
        self.assertContains(response, "The backup schedule nightly backs up its VMs")
        self.assertTrue(Tag.objects.filter(name="prod").exists())

    # what another request does while this one waits for the ownership lock
    def meanwhile(self, change):
        from computes import utils
        real = utils.lock_ownership

        def lock():
            change()
            real()
        return patch("admin.views.lock_ownership", side_effect=lock)

    def test_a_rename_meanwhile_is_cleaned_from_removed_vms_on_delete(self):
        def rename():
            Tag.objects.filter(pk=self.prod.pk).update(name="live")
            InstanceTombstone.objects.filter(pk=self.tombstone.pk).update(tags=["live", "db"])
        with self.meanwhile(rename):
            self.client.post(reverse("admin:tag_delete", args=[self.prod.pk]))
        self.tombstone.refresh_from_db()
        self.assertEqual(self.tombstone.tags, ["db"])

    def test_a_tag_deleted_while_its_rename_waits_is_not_found(self):
        with self.meanwhile(lambda: Tag.objects.filter(pk=self.prod.pk).delete()):
            response = self.client.post(reverse("admin:tag_update", args=[self.prod.pk]), {"name": "live"})
        self.assertEqual(response.status_code, 404)

    def test_a_removed_vm_kept_only_for_the_deleted_tag_goes(self):
        InstanceTombstone.objects.create(uuid="12345678-0000-0000-0000-00000000dd03", name="tagged-only", tags=["prod"])
        self.client.post(reverse("admin:tag_delete", args=[self.prod.pk]))
        self.assertEqual(list(InstanceTombstone.objects.values_list("name", flat=True)), ["gone"])

    def test_a_name_taken_meanwhile_is_refused(self):
        with self.meanwhile(lambda: Tag.objects.create(name="live")):
            response = self.client.post(reverse("admin:tag_update", args=[self.prod.pk]), {"name": "live"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].errors["name"], ["There is a tag with this name already"])
        self.assertEqual(Tag.objects.get(pk=self.prod.pk).name, "prod")

    def test_a_name_taken_is_refused_in_the_reader_s_language(self):
        Tag.objects.create(name="db")
        response = self.client.post(reverse("admin:tag_update", args=[self.prod.pk]), {"name": "db"})
        with translation.override("tr"):  # the message is read in the reader's language
            self.assertEqual(list(response.context["form"].errors["name"]), ["Bu adla bir etiket zaten var"])

    def test_only_superusers(self):
        self.client.force_login(User.objects.create_user("tg-user", password="pw"))
        for url in (reverse("admin:tag_list"), reverse("admin:tag_update", args=[self.prod.pk]),
                    reverse("admin:tag_delete", args=[self.prod.pk])):
            self.assertEqual(self.client.post(url, {"name": "x"}).status_code, 403)
        self.assertEqual(Tag.objects.get().name, "prod")
