"""Tags of VMs and hosts: one list of names, kept with a VM that leaves its
host for a while or moves out of band, and set on the host form."""

from unittest.mock import MagicMock

from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from computes.forms import TagsField, TagsForm
from computes.models import Compute, Tag
from computes.tests.fakes import Domain, no_host_answers
from computes.utils import move_ownership, refresh_instance_database
from instances.models import Instance, InstanceTombstone

UUID = "55555555-5555-5555-5555-555555555555"


class TagsFieldTests(TestCase):
    def test_names_are_kept_in_lower_case_once(self):
        self.assertEqual(TagsField().clean(["Prod", "db", "prod"]), ["prod", "db"])

    def test_a_name_is_letters_digits_and_dot_dash_underscore(self):
        for bad in ("two words", "-lead", "ç", "x" * 33):
            with self.subTest(bad), self.assertRaises(forms.ValidationError):
                TagsField().clean([bad])

    def test_the_box_tells_in_the_reader_s_language_what_a_new_name_adds(self):
        with translation.override("tr"):
            html = TagsForm().as_p()
        self.assertIn('data-add="Etiket ekle: %(tag)s"', html)

    def test_the_tags_are_made_when_saved(self):
        Tag.objects.create(name="prod")
        tags = Tag.named(["prod", "db"])
        self.assertEqual(sorted(t.name for t in tags), ["db", "prod"])
        self.assertEqual(Tag.objects.count(), 2)


class TagsFollowTheVmTests(TestCase):
    def setUp(self):
        self.prod, self.db = Tag.objects.create(name="prod"), Tag.objects.create(name="db")
        self.host_a = self.compute("host-a")
        self.host_b = self.compute("host-b")

    def compute(self, name):
        compute = Compute.objects.create(name=name, hostname=f"{name}.example", login="", password="", type=1)
        compute.__dict__["proxy"] = MagicMock()
        compute.__dict__["status"] = True
        compute.proxy.wvm.listAllDomains.return_value = []
        return compute

    def tag_names(self, compute):
        return sorted(Instance.objects.get(compute=compute, uuid=UUID).tags.values_list("name", flat=True))

    def test_a_vm_with_tags_only_gets_them_back(self):
        Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID).tags.add(self.prod)
        refresh_instance_database(self.host_a)  # undefined for a while
        self.assertEqual(InstanceTombstone.objects.get(uuid=UUID).tags, ["prod"])

        self.host_a.proxy.wvm.listAllDomains.return_value = [Domain("vm", UUID)]
        refresh_instance_database(self.host_a)
        self.assertEqual(self.tag_names(self.host_a), ["prod"])

    def test_a_tag_deleted_meanwhile_is_not_given_back(self):
        Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID).tags.add(self.prod, self.db)
        refresh_instance_database(self.host_a)
        self.db.delete()
        self.host_b.proxy.wvm.listAllDomains.return_value = [Domain("vm", UUID)]
        refresh_instance_database(self.host_b)
        self.assertEqual(self.tag_names(self.host_b), ["prod"])

    def test_a_move_adds_the_tags_to_those_already_there(self):
        source = Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID)
        source.tags.add(self.prod)
        target = Instance.objects.create(compute=self.host_b, name="vm", uuid=UUID)
        target.tags.add(self.db)
        move_ownership(source, target)
        self.assertEqual(self.tag_names(self.host_b), ["db", "prod"])


class HostTagsTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("ht-admin", "ht@example.com", "pw"))
        no_host_answers(self)

    def test_the_host_form_sets_the_tags(self):
        self.client.post(reverse("add_tcp_host"), {"name": "kvm1", "hostname": "192.0.2.1", "login": "wvc",
                                                   "password": "pw", "details": "", "tags": ["Rack-1", "gpu"]})
        compute = Compute.objects.get(name="kvm1")
        self.assertEqual(sorted(compute.tags.values_list("name", flat=True)), ["gpu", "rack-1"])

        self.client.post(reverse("compute_update", args=[compute.id]),
                         {"name": "kvm1", "hostname": "192.0.2.1", "login": "wvc", "password": "", "details": ""})
        self.assertFalse(compute.tags.exists())

    def test_the_socket_form_has_them_too(self):
        self.client.post(reverse("add_socket_host"), {"name": "local", "hostname": "localhost", "details": "",
                                                      "tags": ["lab"]})
        self.assertEqual(list(Compute.objects.get(name="local").tags.values_list("name", flat=True)), ["lab"])

    def test_the_hosts_list_shows_them(self):
        compute = Compute.objects.create(name="kvm1", hostname="192.0.2.1", login="wvc", password="pw", type=1)
        compute.tags.add(Tag.objects.create(name="rack-1"))
        self.assertContains(self.client.get(reverse("computes")), "rack-1")
