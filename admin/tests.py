from django.contrib.auth.models import Group, User
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import reverse
from django.test import TestCase

from accounts.models import UserAttributes


class AdminTestCase(TestCase):
    def setUp(self):
        self.client.login(username="admin", password="admin")

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

        response = self.client.post(reverse("admin:group_delete", args=[group_id]))
        self.assertRedirects(response, reverse("admin:group_list"))

        with self.assertRaises(ObjectDoesNotExist):
            Group.objects.get(id=group_id)

    def test_user_list(self):
        response = self.client.get(reverse("admin:user_list"))
        self.assertEqual(response.status_code, 200)

    def test_users(self):
        response = self.client.get(reverse("admin:user_create"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("admin:user_create"),
            {
                "username": "test",
                "password": "test",
                "max_instances": 1,
                "max_cpus": 1,
                "max_memory": 1024,
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
                "max_instances": 2,
                "max_cpus": 2,
                "max_memory": 2048,
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

        response = self.client.get(reverse("admin:user_block", args=[user_id]))
        user = User.objects.get(id=user_id)
        self.assertFalse(user.is_active)

        response = self.client.get(reverse("admin:user_unblock", args=[user_id]))
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
