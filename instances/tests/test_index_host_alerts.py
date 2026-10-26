"""Host connection errors on the instance list: administrators see which host
and why; other users only learn that a host of their own VMs is unreachable."""

from unittest.mock import PropertyMock, patch

from accounts.models import UserInstance
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance

USER_MESSAGE = "A host of some of your virtual machines cannot be reached right now."


class IndexHostAlertTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tenant", password="pwd")
        self.mine = Compute.objects.create(name="mine-host", hostname="10.0.0.1", type=1, login="u", password="p")
        self.other = Compute.objects.create(name="other-host", hostname="10.0.0.2", type=1, login="u", password="p")
        vm = Instance.objects.create(compute=self.mine, name="tenant-vm", uuid="11111111-1111-1111-1111-111111111111")
        UserInstance.objects.create(instance=vm, user=self.user)

    def get(self, user, down):
        def status(compute):
            return compute.name not in down

        def error(compute):
            return None if status(compute) else f"Connection Failed: no route to {compute.hostname}"

        self.client.force_login(user)
        with patch("instances.views.utils.refr"), patch.object(Compute, "status", property(status)), patch.object(
            Compute, "connection_error", property(error)
        ), patch.object(Instance, "info", new_callable=PropertyMock, return_value=None):
            response = self.client.get(reverse("instances:index"))
        self.assertEqual(response.status_code, 200)
        return response

    def test_user_sees_no_infrastructure_details(self):
        response = self.get(self.user, down={"mine-host", "other-host"})
        self.assertContains(response, USER_MESSAGE, count=1)
        for text in ("mine-host", "other-host", "10.0.0.1", "10.0.0.2", "Connection Failed"):
            self.assertNotContains(response, text)

    def test_user_is_not_told_about_hosts_without_their_vms(self):
        response = self.get(self.user, down={"other-host"})
        self.assertNotContains(response, USER_MESSAGE)
        self.assertNotContains(response, "other-host")

    def test_superuser_sees_each_host_and_its_error(self):
        admin = get_user_model().objects.create_superuser(username="root", password="pwd", email="r@example.com")
        response = self.get(admin, down={"mine-host", "other-host"})
        self.assertContains(response, "Connection Failed: no route to 10.0.0.1")
        self.assertContains(response, "Connection Failed: no route to 10.0.0.2")
        self.assertNotContains(response, USER_MESSAGE)

    def test_global_viewer_sees_each_host_and_its_error(self):
        viewer = get_user_model().objects.create_user(username="viewer", password="pwd")
        viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        response = self.get(viewer, down={"other-host"})
        self.assertContains(response, "Connection Failed: no route to 10.0.0.2")

    def test_global_viewer_sees_each_vms_host_without_the_host_page(self):
        viewer = get_user_model().objects.create_user(username="viewer2", password="pwd")
        viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        response = self.get(viewer, down=set())
        self.assertContains(response, "mine-host")
        self.assertNotContains(response, reverse("overview", args=[self.mine.id]))
