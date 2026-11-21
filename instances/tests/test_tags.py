"""A VM's tags: set by a superuser on its page, shown to everyone who sees the VM."""

from unittest.mock import PropertyMock, patch

from lxml import html as lxml_html

from accounts.models import UserInstance
from computes.models import Compute, Tag
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance, InstanceTombstone
from logs.models import Logs


class VmTagsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("vt-admin", "vt@example.com", "pw")
        self.owner = User.objects.create_user("vt-owner", password="pw")
        compute = Compute.objects.create(name="vt", hostname="192.0.2.5", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="vt-vm", uuid="12345678-0000-0000-0000-00000000bbbb")
        UserInstance.objects.create(user=self.owner, instance=self.vm, is_change=True)

    def post(self, user, tags, shown=None):
        """tags sent from a form that showed shown (the VM's tags now if None)"""
        self.client.force_login(user)
        if shown is None:
            shown = self.names()
        with patch("instances.models.wvmInstance"):
            return self.client.post(reverse("instances:set_tags", args=[self.vm.id]), {"tags": tags, "initial-tags": shown})

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

    def test_the_same_tags_again_are_no_change(self):
        self.post(self.admin, ["prod"])
        self.post(self.admin, ["PROD"])
        self.assertEqual(Logs.objects.filter(message__startswith="VM vt-vm: tags").count(), 1)

    def test_a_form_shown_before_a_rename_keeps_the_new_name(self):
        self.vm.tags.add(Tag.objects.create(name="prod"))
        Tag.objects.filter(name="prod").update(name="production")  # the Tags page renames it meanwhile
        self.post(self.admin, ["prod"], shown=["prod"])
        self.assertEqual(self.names(), ["production"])
        self.assertFalse(Tag.objects.filter(name="prod").exists())
        self.assertFalse(Logs.objects.filter(message__startswith="VM vt-vm: tags").exists())

    def test_the_form_carries_the_tags_it_showed(self):
        from computes.forms import TagsForm
        self.assertIn('name="initial-tags" value="prod"', str(TagsForm(initial={"tags": ["prod"]})["tags"]))

    def test_a_bad_name_changes_nothing(self):
        self.vm.tags.add(Tag.objects.create(name="prod"))
        self.post(self.admin, ["two words"])
        self.assertEqual(self.names(), ["prod"])

    def test_an_owner_cannot_set_them(self):
        self.assertEqual(self.post(self.owner, ["prod"]).status_code, 403)
        self.assertEqual(self.names(), [])
        self.assertFalse(Tag.objects.exists())

    def test_a_vm_gone_meanwhile_keeps_its_removed_record(self):
        from computes import utils
        real = utils.lock_ownership

        def lock():
            utils.forget(Instance.objects.get(pk=self.vm.pk))  # the host no longer lists it
            real()
        self.vm.tags.add(Tag.objects.create(name="prod"))
        with patch("instances.views.lock_ownership", side_effect=lock):
            response = self.post(self.admin, ["db"])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(InstanceTombstone.objects.get().tags, ["prod"])
        self.assertFalse(Logs.objects.filter(message__startswith="VM vt-vm: tags").exists())

    def test_the_host_s_vm_list_and_the_user_s_vms_show_them(self):
        self.vm.tags.add(Tag.objects.create(name="prod"))
        self.client.force_login(self.admin)
        with patch("computes.views.utils.refresh_instance_database"), patch("computes.views.vm_states", return_value={}), \
                patch("computes.views.read_list_rows"):
            self.assertContains(self.client.get(reverse("instances", args=[self.vm.compute_id])), "prod")
        self.assertContains(self.client.get(reverse("accounts:account", args=[self.owner.id])), "prod")

    def test_the_host_s_vm_list_shows_three_and_the_others_behind_an_ellipsis(self):
        self.vm.tags.add(*(Tag.objects.create(name=name) for name in ("a1", "b2", "c3", "d4")))
        self.client.force_login(self.admin)
        with patch("computes.views.utils.refresh_instance_database"), patch("computes.views.vm_states", return_value={}), \
                patch("computes.views.read_list_rows"):
            page = lxml_html.fromstring(self.client.get(reverse("instances", args=[self.vm.compute_id])).content)
        # the VM list's badges: each chooses its tag in the tag filter
        self.assertEqual(page.xpath("//td//button[@data-tag-filter][not(ancestor::*[@hidden])]/@data-tag-filter"),
                         ["a1", "b2", "c3"])
        self.assertEqual(page.xpath("//button[@data-show-tags]/@title"), ["d4"])
        # the tags "…" shows take the focus from it (table_filter.js), not buttons here
        self.assertEqual(page.xpath("//button[@data-show-tags]/following-sibling::span[1]/@tabindex"), ["-1"])

    def test_the_vm_list_shows_them(self):
        self.vm.tags.add(Tag.objects.create(name="prod"))
        html = render_to_string("instance_name_cell.html", {"instance": self.vm})
        self.assertIn("prod", html)

    def test_the_vm_list_shows_three_and_the_others_behind_an_ellipsis(self):
        self.vm.tags.add(*(Tag.objects.create(name=name) for name in ("a1", "b2", "c3", "d4", "e5")))
        cell = lxml_html.fromstring(render_to_string("instance_name_cell.html", {"instance": self.vm}))
        self.assertEqual(cell.xpath("//button[not(ancestor::*[@hidden])]/@data-tag-filter"), ["a1", "b2", "c3"])
        # "…" names the others and shows them when pressed (table_filter.js), with the keyboard too
        (more,) = cell.xpath("//button[@data-show-tags]")
        self.assertEqual((more.get("title"), more.text_content().strip()), ("d4, e5", "… more tags"))
        self.assertEqual(cell.xpath("//*[@hidden]//button/@data-tag-filter"), ["d4", "e5"])


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

    def test_the_tag_list_has_the_tags_of_the_vms_listed_with_how_many(self):
        Instance.objects.create(compute=Compute.objects.get(), name="bare", uuid="12345678-0000-0000-0000-00000000cc03")
        doc = self.page(self.admin)
        # pills as the states', below them
        pills = doc.xpath("//nav[preceding-sibling::nav//div[@id='state-pills']]//div[@id='tag-pills']/button")
        self.assertEqual([pill.get("data-pill") for pill in pills], ["", "-", "prod", "secret", "web"])
        self.assertEqual([" ".join(pill.text_content().split()) for pill in pills],
                         ["All tags", "No tag 1", "prod 1", "secret 1", "web 1"])
        # table_filter.js counts them again as the search and the state change
        self.assertEqual(doc.xpath("//div[@id='tag-pills']//@data-count-tag"), ["-", "prod", "secret", "web"])
        self.assertEqual(doc.xpath("//tr[@data-tags]/@data-tags"), ["", "prod web", "secret"])
        # a badge chooses its tag in the list
        self.assertEqual(doc.xpath("//tr//button[@data-tag-filter]/@data-tag-filter"), ["prod", "web", "secret"])

    def test_the_most_used_eight_show_the_others_behind_an_ellipsis(self):
        from types import SimpleNamespace
        # ten tags, t0 on ten VMs ... t9 on one: by how many have them, the first eight shown
        rows = [SimpleNamespace(tags=SimpleNamespace(all=lambda n=n: [SimpleNamespace(name=f"t{i}") for i in range(n)]))
                for n in range(1, 11)]
        counts = Tag.counts(rows)
        self.assertEqual(counts[0][:3], [("t0", 10), ("t1", 9), ("t2", 8)])
        doc = lxml_html.fromstring(render_to_string("common/tag_filter.html", {"tags": counts}))
        shown = doc.xpath("//div[@id='tag-pills']/button/@data-pill")
        self.assertEqual(shown, ["", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7"])
        (more,) = doc.xpath("//button[@data-show-tags]")
        self.assertEqual(" ".join(more.text_content().split()), "… More tags 2")
        self.assertEqual(more.xpath(".//@data-more-count"), [""])  # table_filter.js counts them again
        self.assertEqual(doc.xpath("//*[@hidden]/button/@data-pill"), ["t8", "t9"])

    def test_an_owner_sees_only_the_tags_of_their_vms(self):
        doc = self.page(self.owner)
        self.assertEqual(doc.xpath("//div[@id='tag-pills']/button/@data-pill"), ["", "prod", "web"])
        self.assertEqual(doc.xpath("//tr[@data-tags]/@data-tags"), ["prod web"])

    def test_no_tags_no_tag_list(self):
        Tag.objects.all().delete()
        self.assertEqual(self.page(self.admin).xpath("//*[@id='tag-pills' or @id='tag-filter']"), [])


class TagsApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.client.force_login(User.objects.create_superuser("ta-admin", "ta@example.com", "pw"))
        self.compute = Compute.objects.create(name="ta", hostname="192.0.2.8", login="u", password="p", type=1)
        Compute.objects.create(name="ta2", hostname="192.0.2.9", login="u", password="p", type=1)
        prod = Tag.objects.create(name="prod")
        self.compute.tags.add(prod)
        self.vm = Instance.objects.create(compute=self.compute, name="web", uuid="12345678-0000-0000-0000-00000000ee01")
        self.vm.tags.add(prod, Tag.objects.create(name="web"))
        Instance.objects.create(compute=self.compute, name="db", uuid="12345678-0000-0000-0000-00000000ee02")

    def get(self, url):
        with patch("instances.api.viewsets.host_domain_states"), \
                patch("instances.api.viewsets.utils.refresh_instance_database"):
            return self.client.get(url).json()

    def test_the_vm_lists_give_the_tags_and_filter_by_one(self):
        for url in ("/api/v1/instances/", f"/api/v1/computes/{self.compute.id}/instances/"):
            with self.subTest(url):
                self.assertEqual(sorted((vm["name"], vm["tags"]) for vm in self.get(url)),
                                 [("db", []), ("web", ["prod", "web"])])
                self.assertEqual([vm["name"] for vm in self.get(url + "?tag=prod")], ["web"])

    def test_the_hosts_give_the_tags_and_filter_by_one(self):
        self.assertEqual([(c["name"], c["tags"]) for c in self.client.get("/api/v1/computes/").json()],
                         [("ta", ["prod"]), ("ta2", [])])
        self.assertEqual([c["name"] for c in self.client.get("/api/v1/computes/?tag=prod").json()], ["ta"])
        self.assertEqual([c["name"] for c in self.client.get("/api/v1/computes/?tag=%20PROD%20").json()], ["ta"])

    def test_a_tag_asked_of_one_host_is_no_filter(self):
        self.assertEqual(self.client.get(f"/api/v1/computes/{self.compute.id}/?tag=other").status_code, 200)

    def test_the_tags_are_not_set_through_the_api(self):
        with patch("computes.models.Compute.clean"):  # the host is not reached
            response = self.client.patch(f"/api/v1/computes/{self.compute.id}/", {"tags": [], "details": "rack 2"},
                                         content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.compute.refresh_from_db()
        self.assertEqual((self.compute.details, list(self.compute.tags.values_list("name", flat=True))),
                         ("rack 2", ["prod"]))
