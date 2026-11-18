"""A VM's tags: set by a superuser on its page, shown to everyone who sees the VM."""

from unittest.mock import PropertyMock, patch

from lxml import html as lxml_html

from accounts.models import UserInstance
from computes.models import Compute, Tag
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from logs.models import Logs


class VmTagsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("vt-admin", "vt@example.com", "pw")
        self.owner = User.objects.create_user("vt-owner", password="pw")
        compute = Compute.objects.create(name="vt", hostname="192.0.2.5", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="vt-vm", uuid="12345678-0000-0000-0000-00000000bbbb")
        UserInstance.objects.create(user=self.owner, instance=self.vm, is_change=True)

    def post(self, user, tags):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance"):
            return self.client.post(reverse("instances:set_tags", args=[self.vm.id]), {"tags": tags})

    def names(self):
        return sorted(self.vm.tags.values_list("name", flat=True))

    def test_a_superuser_sets_and_clears_them(self):
        Tag.objects.create(name="prod")
        self.post(self.admin, ["prod", "New-One"])
        self.assertEqual(self.names(), ["new-one", "prod"])
        self.post(self.admin, [])
        self.assertEqual(self.names(), [])
        self.assertEqual(list(Logs.objects.filter(message__startswith="VM").order_by("id").values_list("message", flat=True)),
                         ["VM vt-vm: tags new-one, prod", "VM vt-vm: tags none"])

    def test_a_bad_name_changes_nothing(self):
        self.vm.tags.add(Tag.objects.create(name="prod"))
        self.post(self.admin, ["two words"])
        self.assertEqual(self.names(), ["prod"])

    def test_an_owner_cannot_set_them(self):
        self.assertEqual(self.post(self.owner, ["prod"]).status_code, 403)
        self.assertEqual(self.names(), [])
        self.assertFalse(Tag.objects.exists())

    def test_the_vm_list_shows_them(self):
        self.vm.tags.add(Tag.objects.create(name="prod"))
        html = render_to_string("instance_name_cell.html", {"instance": self.vm})
        self.assertIn("prod", html)


class VmListTagFilterTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("tf-admin", "tf@example.com", "pw")
        self.owner = User.objects.create_user("tf-owner", password="pw")
        compute = Compute.objects.create(name="tf", hostname="192.0.2.6", login="u", password="p", type=1)
        mine = Instance.objects.create(compute=compute, name="mine", uuid="12345678-0000-0000-0000-00000000cc01")
        other = Instance.objects.create(compute=compute, name="other", uuid="12345678-0000-0000-0000-00000000cc02")
        UserInstance.objects.create(user=self.owner, instance=mine)
        mine.tags.add(Tag.objects.create(name="web"), Tag.objects.create(name="prod"))
        other.tags.add(Tag.objects.create(name="secret"))

    def page(self, user):
        self.client.force_login(user)
        with patch("instances.views.refresh_instance_database"), \
                patch("instances.views.utils.vm_states", return_value={}), \
                patch("instances.views.utils.read_list_rows"), \
                patch.object(Compute, "status", new_callable=PropertyMock, return_value=True):
            return lxml_html.fromstring(self.client.get(reverse("instances:index")).content)

    def test_the_tag_list_has_the_tags_of_the_vms_listed(self):
        doc = self.page(self.admin)
        self.assertEqual(doc.xpath("//select[@id='tag-filter']/option/@value"), ["", "prod", "secret", "web"])
        self.assertEqual(doc.xpath("//tr[@data-tags]/@data-tags"), ["prod web", "secret"])

    def test_an_owner_sees_only_the_tags_of_their_vms(self):
        doc = self.page(self.owner)
        self.assertEqual(doc.xpath("//select[@id='tag-filter']/option/@value"), ["", "prod", "web"])
        self.assertEqual(doc.xpath("//tr[@data-tags]/@data-tags"), ["prod web"])

    def test_no_tags_no_tag_list(self):
        Tag.objects.all().delete()
        self.assertEqual(self.page(self.admin).xpath("//select[@id='tag-filter']"), [])
