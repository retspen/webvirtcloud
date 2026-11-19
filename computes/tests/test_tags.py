"""Tags of VMs and hosts: one list of names, kept with a VM that leaves its
host for a while or moves out of band, and set on the host form."""

from unittest.mock import MagicMock, patch

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
        self.assertEqual(TagsField().clean(["x" * 12]), ["x" * 12])
        # a tag made before the limit can still be given
        Tag.objects.create(name="y" * 20)
        self.assertEqual(TagsField().clean(["y" * 20]), ["y" * 20])
        for bad in ("two words", "-lead", "ç", "x" * 13):
            with self.subTest(bad), self.assertRaises(forms.ValidationError):
                TagsField().clean([bad])

    def test_the_box_tells_in_the_reader_s_language_what_a_new_name_adds(self):
        with translation.override("tr"):
            html = TagsForm().as_p()
        self.assertIn('data-add="Etiket ekle: %(tag)s"', html)
        # and what a new name may be, shown when the one typed cannot be a tag
        self.assertIn('data-rule="Yeni etiket: a-z harfleri, rakamlar, nokta, tire ve alt çizgi, harf ya da rakamla başlar; '
                      'en fazla 12 karakter"', html)

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
                         {"name": "kvm1", "hostname": "192.0.2.1", "login": "wvc", "password": "", "details": "",
                          "initial-tags": ["gpu", "rack-1"]})
        self.assertFalse(compute.tags.exists())

    def test_a_form_shown_before_a_rename_keeps_the_new_name(self):
        compute = Compute.objects.create(name="kvm1", hostname="192.0.2.1", login="wvc", password="pw", type=1)
        compute.tags.add(Tag.objects.create(name="prod"))
        # the form carries the tags it showed, and sends them back unchanged
        self.assertContains(self.client.get(reverse("compute_update", args=[compute.id])),
                            '<input type="hidden" name="initial-tags" value="prod">', html=True)
        Tag.objects.filter(name="prod").update(name="production")  # the Tags page renames it meanwhile
        self.client.post(reverse("compute_update", args=[compute.id]),
                         {"name": "kvm1b", "hostname": "192.0.2.1", "login": "wvc", "password": "", "details": "",
                          "tags": ["prod"], "initial-tags": ["prod"]})
        compute.refresh_from_db()
        self.assertEqual((compute.name, list(compute.tags.values_list("name", flat=True))), ("kvm1b", ["production"]))
        self.assertFalse(Tag.objects.filter(name="prod").exists())

    def test_a_form_shown_again_with_an_error_carries_the_tags_first_shown(self):
        compute = Compute.objects.create(name="kvm1", hostname="192.0.2.1", login="wvc", password="pw", type=1)
        compute.tags.add(Tag.objects.create(name="production"))  # renamed from prod since the form was shown
        response = self.client.post(reverse("compute_update", args=[compute.id]),
                                    {"name": "kvm1", "hostname": "bad host", "login": "wvc", "password": "",
                                     "details": "", "tags": ["prod"], "initial-tags": ["prod"]})
        self.assertContains(response, '<input type="hidden" name="initial-tags" value="prod">', html=True)

    def test_the_same_tags_in_another_order_are_no_change(self):
        compute = Compute.objects.create(name="kvm1", hostname="192.0.2.1", login="wvc", password="pw", type=1)
        compute.tags.add(Tag.objects.create(name="production"))
        self.client.post(reverse("compute_update", args=[compute.id]),
                         {"name": "kvm1", "hostname": "192.0.2.1", "login": "wvc", "password": "", "details": "",
                          "tags": ["b", "a"], "initial-tags": ["a", "b"]})
        self.assertEqual(list(compute.tags.values_list("name", flat=True)), ["production"])

    def test_a_tag_deleted_meanwhile_is_made_again(self):
        compute = Compute.objects.create(name="kvm1", hostname="192.0.2.1", login="wvc", password="pw", type=1)
        compute.tags.add(Tag.objects.create(name="gpu"))
        from computes import utils
        real = utils.lock_ownership

        def lock():  # the Tags page deletes it while the form waits for the lock
            Tag.objects.filter(name="gpu").delete()
            real()
        with patch("computes.forms.lock_ownership", side_effect=lock):
            response = self.client.post(reverse("compute_update", args=[compute.id]),
                                        {"name": "kvm1b", "hostname": "192.0.2.1", "login": "wvc", "password": "",
                                         "details": "", "tags": ["gpu"]})
        self.assertEqual(response.status_code, 302)
        compute.refresh_from_db()
        self.assertEqual((compute.name, list(compute.tags.values_list("name", flat=True))), ("kvm1b", ["gpu"]))

    def test_the_socket_form_has_them_too(self):
        self.client.post(reverse("add_socket_host"), {"name": "local", "hostname": "localhost", "details": "",
                                                      "tags": ["lab"]})
        self.assertEqual(list(Compute.objects.get(name="local").tags.values_list("name", flat=True)), ["lab"])

    def test_the_hosts_list_shows_them(self):
        compute = Compute.objects.create(name="kvm1", hostname="192.0.2.1", login="wvc", password="pw", type=1)
        compute.tags.add(*(Tag.objects.create(name=name) for name in ("rack-1", "gpu", "ssd", "lab")))
        response = self.client.get(reverse("computes"))
        self.assertContains(response, 'data-show-tags title="ssd"')  # three, and "…" for the others
        self.assertContains(response, "rack-1")
        self.assertContains(response, '<button type="button" class="nav-link py-1 px-2" data-pill="rack-1" '
                                      'aria-pressed="false">rack-1 <span class="badge text-bg-light ms-1" data-count-tag="rack-1">1</span>'
                                      '</button>',
                            html=True)
        self.assertContains(response, 'data-tag-filter="rack-1"')
        # a search and a tag that match no host: the page says so and clears them
        self.assertContains(response, 'id="no-match"')
        self.assertContains(response, 'id="clear-filters"')
        self.assertContains(response, 'data-tags="gpu lab rack-1 ssd"')
