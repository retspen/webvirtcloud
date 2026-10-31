"""Each delete page says what deleting its object does, besides naming it."""

from accounts.models import UserInstance, UserSSHKey
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from instances.models import Flavor, Instance, InstanceTombstone
from lxml import html

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGJ5dGVzLWZvci10aGUtZGVsZXRlLXBhZ2UtdGVzdA== page@example.com"


class DeletePageTests(TestCase):
    def test_every_delete_page_says_what_deleting_does(self):
        admin = get_user_model().objects.create_superuser("del-admin", "da@example.com", "pw")
        user = get_user_model().objects.create_user("del-user", password="pw")
        compute = Compute.objects.create(name="del-host", hostname="192.0.2.9", login="u", password="p", type=1)
        vm = Instance.objects.create(compute=compute, name="del-vm", uuid="d0000000-0000-4000-8000-000000000001")
        pages = {
            reverse("compute_delete", args=[compute.id]): "their owners are kept for 30 days on the Removed VMs page",
            reverse("admin:user_delete", args=[user.id]): "the VMs themselves stay",
            reverse("admin:group_delete", args=[Group.objects.create(name="del-group").id]): "lose the permissions",
            reverse("admin:tombstone_delete", args=[InstanceTombstone.objects.create(uuid=vm.uuid, name="gone").id]):
                "no longer get the VM back",
            reverse("accounts:user_instance_delete", args=[UserInstance.objects.create(user=user, instance=vm).id]):
                "the VM itself is not changed",
            reverse("instances:flavor_delete", args=[Flavor.objects.create(label="del-flavor", memory=512, vcpu=1, disk=1).id]):
                "VMs made from it keep their size",
        }
        key = UserSSHKey.objects.create(user=admin, keyname="del-key", keypublic=KEY)
        pages[reverse("accounts:ssh_key_delete", args=[key.id])] = "VMs that already have it keep it"
        self.client.force_login(admin)
        for url, consequence in pages.items():
            with self.subTest(url=url):
                card = html.fromstring(self.client.get(url).content).xpath("//div[contains(@class, 'border-danger')]")
                self.assertEqual(len(card), 1)
                self.assertIn(consequence, card[0].text_content())
                self.assertNotIn("Are you sure", card[0].text_content())
