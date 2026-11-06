from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.shortcuts import reverse
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from lxml import html

from accounts.models import UserAttributes
from logs.models import Logs


class AdminTestCase(TestCase):
    def setUp(self):
        self.client.login(request=RequestFactory().get("/"), username="admin", password="admin")
        Logs.objects.all().delete()  # the login's row

    def test_group_list(self):
        response = self.client.get(reverse("admin:group_list"))
        self.assertEqual(response.status_code, 200)

    def test_groups(self):
        response = self.client.get(reverse("admin:group_create"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("admin:group_create"), {"name": "Test Group"}
        )
        self.assertRedirects(response, reverse("admin:group_list"))

        group = Group.objects.get(name="Test Group")
        group_id = group.id

        response = self.client.get(reverse("admin:group_update", args=[group_id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("admin:group_update", args=[group_id]), {"name": "Updated Group Test"}
        )
        self.assertRedirects(response, reverse("admin:group_list"))

        group = Group.objects.get(id=group_id)
        self.assertEqual(group.name, "Updated Group Test")

        response = self.client.get(reverse("admin:group_delete", args=[group_id]))
        self.assertEqual(response.status_code, 200)
        # the shared confirmation page names what it deletes
        self.assertContains(response, "<title>Delete Updated Group Test</title>", html=True)

        response = self.client.post(reverse("admin:group_delete", args=[group_id]))
        self.assertRedirects(response, reverse("admin:group_list"))

        with self.assertRaises(ObjectDoesNotExist):
            Group.objects.get(id=group_id)

    def test_group_form_lists_its_members_first(self):
        for name in ("zed", "bob", "amy"):
            User.objects.create_user(name)
        User.objects.filter(username="amy").update(first_name="Amy", last_name="Adams")
        group = Group.objects.create(name="Ops")
        group.user_set.add(User.objects.get(username="zed"))

        page = html.fromstring(self.client.get(reverse("admin:group_update", args=[group.id])).content)
        boxes = page.xpath("//div[contains(@class, 'searchable')]/label")
        names = [box.text_content().split()[0] for box in boxes]
        self.assertEqual(names, ["zed", "admin", "amy", "bob"])
        self.assertIn("Amy Adams", boxes[2].get("data-search"))
        self.assertEqual(page.xpath("//input[@id='filter']/@data-forget"), [""])
        self.assertEqual(page.xpath("//form[@id='create-update']//button[@type='submit']/text()"), ["Save changes"])
        page = html.fromstring(self.client.get(reverse("admin:group_create")).content)
        self.assertEqual(page.xpath("//form[@id='create-update']//button[@type='submit']/text()"), ["Create group"])

    def test_user_list(self):
        response = self.client.get(reverse("admin:user_list"))
        self.assertEqual(response.status_code, 200)

    def test_user_list_shows_who_can_clone_in_queries_independent_of_the_users(self):
        clone = Permission.objects.get(content_type__app_label="instances", codename="clone_instances")
        User.objects.create_user("direct").user_permissions.add(clone)
        group = Group.objects.create(name="Cloners")
        group.permissions.add(clone)
        User.objects.create_user("by-group").groups.add(group)
        blocked = User.objects.create_user("blocked", is_active=False)
        blocked.user_permissions.add(clone)
        User.objects.create_user("plain")

        def rows():
            with CaptureQueriesContext(connection) as queries:
                page = html.fromstring(self.client.get(reverse("admin:user_list")).content)
            return {item.xpath(".//a[contains(@class, 'fw-semibold')]")[0].text: "Can clone" in item.text_content()
                    for item in page.xpath("//div[contains(@class, 'list-group-item')]")}, len(queries)

        shown, count = rows()
        self.assertEqual({name: shown[name] for name in ("direct", "by-group", "blocked", "plain", "admin")},
                         {"direct": True, "by-group": True, "blocked": False, "plain": False, "admin": False})
        for i in range(5):
            User.objects.create_user(f"more-{i}").user_permissions.add(clone)
        self.assertEqual(rows()[1], count)

    def test_users(self):
        response = self.client.get(reverse("admin:user_create"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("admin:user_create"),
            {
                "username": "test",
                "password": "Wvc-created-9",
                "role": "user",
                "max_instances": 1,
                "max_cpus": 1,
                "max_memory": 1,  # GiB
                "max_disk_size": 4,
            },
        )
        self.assertRedirects(response, reverse("admin:user_list"))

        user = User.objects.get(username="test")
        user_id = user.id

        ua: UserAttributes = UserAttributes.objects.get(user_id=user_id)
        self.assertEqual(ua.user_id, user_id)
        self.assertEqual(ua.max_instances, 1)
        self.assertEqual(ua.max_cpus, 1)
        self.assertEqual(ua.max_memory, 1024)
        self.assertEqual(ua.max_disk_size, 4)

        response = self.client.get(reverse("admin:user_update", args=[user_id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("admin:user_update", args=[user_id]),
            {
                "username": "utest",
                "role": "user",
                "max_instances": 2,
                "max_cpus": 2,
                "max_memory": 2,  # GiB
                "max_disk_size": 8,
            },
        )
        self.assertRedirects(response, reverse("admin:user_list"))

        user = User.objects.get(id=user_id)
        self.assertEqual(user.username, "utest")

        ua = UserAttributes.objects.get(user_id=user_id)
        self.assertEqual(ua.user_id, user_id)
        self.assertEqual(ua.max_instances, 2)
        self.assertEqual(ua.max_cpus, 2)
        self.assertEqual(ua.max_memory, 2048)
        self.assertEqual(ua.max_disk_size, 8)

        # Blocking changes state, so a GET (e.g. an <img> tag) must not do it.
        User.objects.filter(id=user_id).update(is_active=True)
        response = self.client.get(reverse("admin:user_block", args=[user_id]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.get(id=user_id).is_active)

        response = self.client.post(reverse("admin:user_block", args=[user_id]))
        user = User.objects.get(id=user_id)
        self.assertFalse(user.is_active)

        response = self.client.get(reverse("admin:user_unblock", args=[user_id]))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(User.objects.get(id=user_id).is_active)

        response = self.client.post(reverse("admin:user_unblock", args=[user_id]))
        user = User.objects.get(id=user_id)
        self.assertTrue(user.is_active)

        response = self.client.get(reverse("admin:user_delete", args=[user_id]))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("admin:user_delete", args=[user_id]))
        self.assertRedirects(response, reverse("admin:user_list"))

        with self.assertRaises(ObjectDoesNotExist):
            User.objects.get(id=user_id)

    def test_logs(self):
        response = self.client.get(reverse("admin:logs"))
        self.assertEqual(response.status_code, 200)

    def test_logs_show_result_and_ip(self):
        Logs.objects.create(message="first", success=True, ip="192.0.2.7")
        Logs.objects.create(message="second", success=False)
        Logs.objects.create(message="third")
        response = self.client.get(reverse("admin:logs"))
        self.assertContains(response, "Done")
        self.assertContains(response, "Failed")
        self.assertContains(response, "Unknown")
        self.assertContains(response, "192.0.2.7")

    def test_logs_order_ties_by_id(self):
        first = Logs.objects.create(message="first")
        second = Logs.objects.create(message="second")
        Logs.objects.filter(id__in=[first.id, second.id]).update(date=first.date)
        response = self.client.get(reverse("admin:logs"))
        self.assertEqual([log.id for log in response.context["logs"]], [second.id, first.id])

    def test_logs_bad_page_numbers(self):
        Logs.objects.create(message="entry")
        response = self.client.get(reverse("admin:logs"), {"page": "abc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["logs"].number, 1)
        response = self.client.get(reverse("admin:logs"), {"page": "999"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["logs"].number, response.context["logs"].paginator.num_pages)
