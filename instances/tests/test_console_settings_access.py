"""
The console settings form is rendered only for users who may change console
settings, which is the rule update_console enforces: a superuser, or an owner
with both is_change and is_vnc; not for is_staff or the global view_instances
permission. The form never carries the VNC password: it says whether one is
set.
"""
from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance

VNC_PASSWORD = "s3cretVNCpass"


class ConsoleSettingsAccessTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        view_perm = Permission.objects.get(codename="view_instances")
        self.superuser = User.objects.create_superuser(
            username="vncpw_super", email="vncpw_super@example.com", password="x"
        )
        self.staff_viewer = User.objects.create_user(
            username="vncpw_staff_viewer", password="x", is_staff=True
        )
        self.staff_viewer.user_permissions.add(view_perm)
        self.staff_owner = User.objects.create_user(
            username="vncpw_staff_owner", password="x", is_staff=True
        )
        self.vnc_owner = User.objects.create_user(username="vncpw_vnc_owner", password="x")

        self.compute = Compute.objects.create(
            name="vncpw-compute", hostname="127.0.0.1:1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="vncpw-vm",
            uuid="cccccccc-dddd-eeee-ffff-000000000000",
        )
        UserInstance.objects.create(
            instance=self.instance, user=self.staff_owner, is_change=True, is_vnc=False
        )
        UserInstance.objects.create(
            instance=self.instance, user=self.vnc_owner, is_change=True, is_vnc=True
        )

    def _detail_page(self, user):
        self.client.force_login(user)
        with patch("instances.models.wvmInstance") as mock_wvm, patch.object(
            Compute, "status", new_callable=PropertyMock, return_value=True
        ):
            proxy = mock_wvm.return_value
            proxy.get_memory.return_value = 1024
            proxy.get_cur_memory.return_value = 1024
            proxy.get_max_memory.return_value = 4096
            proxy.get_networks.return_value = []
            proxy.get_ifaces.return_value = []
            proxy.get_hostdevs.return_value = ([], [], [])
            proxy.get_storages.return_value = []
            proxy.get_console_passwd.return_value = VNC_PASSWORD
            proxy.get_console_type.return_value = "vnc"
            proxy.get_status.return_value = 5
            proxy.get_disk_devices.return_value = []
            proxy.get_media_devices.return_value = []
            proxy.get_net_devices.return_value = []
            response = self.client.get(
                reverse("instances:instance", args=[self.instance.id])
            )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_only_users_who_may_change_the_console_see_its_settings(self):
        form = reverse("instances:update_console", args=[self.instance.id])
        for user, shown in ((self.staff_viewer, False), (self.staff_owner, False),
                            (self.vnc_owner, True), (self.superuser, True)):
            with self.subTest(user.username):
                page = self._detail_page(user)
                self.assertEqual(form in page, shown)
                self.assertNotIn(VNC_PASSWORD, page)
