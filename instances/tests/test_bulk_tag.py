"""A superuser adds a tag to, or removes it from, the VMs chosen on the VM
list, with a log row for each VM it changes; owners have no such buttons."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from lxml import html

from accounts.models import UserInstance
from computes.models import Compute, Tag
from instances.models import Instance
from logs.models import Logs


class BulkTagTestCase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("bt-admin", "bt@example.com", "pw"))
        compute = Compute.objects.create(name="bt-host", hostname="127.0.0.1", login="", password="", type=4)
        self.vms = [Instance.objects.create(compute=compute, name=f"bt-vm{n}", uuid=f"00000000-0000-4000-8000-00000000010{n}")
                    for n in (1, 2)]
        # the list page asks each VM's host: not this machine's libvirt, whose last error would reach other tests
        patch.object(Instance, "proxy", property(lambda vm: MagicMock(**{"get_status.return_value": 5}))).start()
        self.addCleanup(patch.stopall)

    def post(self, action, tag, vms):
        self.client.cookies.pop("messages", None)
        response = self.client.post(reverse("instances:bulk_tag"), {"action": action, "tag": tag,
                                                                     "vm": [vm.pk for vm in vms]})
        return [str(m) for m in get_messages(response.wsgi_request)]

    def vm_tags(self):
        return [sorted(vm.tags.values_list("name", flat=True)) for vm in self.vms]

    def test_added_and_removed_with_a_row_for_each_vm_changed(self):
        self.vms[0].tags.add(Tag.objects.create(name="web"))
        self.assertEqual(self.post("tag_add", " Web ", self.vms), ["Tag web added to 1 VM"])  # vm1 had it
        self.assertEqual(self.vm_tags(), [["web"], ["web"]])
        self.assertEqual(self.post("tag_remove", "web", self.vms), ["Tag web removed from 2 VMs"])
        self.assertEqual(self.vm_tags(), [[], []])
        rows = list(Logs.objects.filter(instance__startswith="bt-vm").order_by("pk").values_list("instance", "message"))
        self.assertEqual([(vm, message.split(": ")[-1]) for vm, message in rows],
                         [("bt-vm2", "tag web"), ("bt-vm1", "untag web"), ("bt-vm2", "untag web")])

    def test_a_wrong_name_or_unknown_tag_is_refused(self):
        self.assertEqual(self.post("tag_add", "", self.vms), ["Choose the VMs and write the tag"])
        self.assertIn("A tag is letters a-z", self.post("tag_add", "no spaces", self.vms)[0])
        self.assertEqual(self.post("tag_remvoe", "web", self.vms), ["Choose the VMs and write the tag"])  # no add
        self.assertEqual(self.post("tag_remove", "none", self.vms), ["There is no tag none"])
        many = self.client.post(reverse("instances:bulk_tag"), {"action": "tag_add", "tag": "web",
                                                                 "vm": [str(n) for n in range(1, 502)]})
        self.assertIn("at most 500 VMs", " ".join(map(str, get_messages(many.wsgi_request))))
        self.client.cookies.pop("messages", None)
        self.assertEqual(self.vm_tags(), [[], []])
        Instance.objects.filter(pk__in=[vm.pk for vm in self.vms]).delete()
        self.assertEqual(self.post("tag_add", "fresh", self.vms), ["Choose the VMs and write the tag"])  # VMs gone
        self.assertFalse(Tag.objects.exists())  # none made by a refusal

    def test_owners_may_not(self):
        owner = get_user_model().objects.create_user("bt-owner", password="pw")
        UserInstance.objects.create(instance=self.vms[0], user=owner)
        self.client.force_login(owner)
        response = self.client.post(reverse("instances:bulk_tag"), {"action": "tag_add", "tag": "web", "vm": [self.vms[0].pk]})
        self.assertEqual(response.status_code, 403)
        with patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.refresh_instance_database"), patch("instances.views.utils.read_list_rows"):
            page = html.fromstring(self.client.get(reverse("instances:index")).content)
        self.assertFalse(page.xpath("//button[starts-with(@value, 'tag_')]"))

    def test_the_list_offers_them_to_a_superuser(self):
        with patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.refresh_instance_database"), patch("instances.views.utils.read_list_rows"):
            page = html.fromstring(self.client.get(reverse("instances:index")).content)
        (form,) = page.xpath("//form[@id='bulk-power']")
        tag_buttons = form.xpath(".//button[starts-with(@value, 'tag_')]")
        self.assertEqual([b.get("value") for b in tag_buttons], ["tag_add", "tag_remove"])
        self.assertEqual({b.get("formaction") for b in tag_buttons}, {reverse("instances:bulk_tag")})
        self.assertTrue(form.xpath(".//input[@name='tag']"))
        # every tag offered, also one no VM has
        Tag.objects.create(name="hosts-only")
        with patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.refresh_instance_database"), patch("instances.views.utils.read_list_rows"):
            page = html.fromstring(self.client.get(reverse("instances:index")).content)
        self.assertEqual(page.xpath("//datalist[@id='bulk-tag-names']/option/@value"), ["hosts-only"])
