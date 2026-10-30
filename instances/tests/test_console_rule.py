"""
One rule decides who may open a VM's console (noVNC page, novncd, the
virt-viewer .vv file, the VDI URL): a superuser or an owner of the VM. The
global view_instances permission is read-only.
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance
from instances.utils import can_open_console


class CanOpenConsoleTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="cons_super", email="cons_super@example.com", password="x"
        )
        self.owner = User.objects.create_user(username="cons_owner", password="x")
        self.inactive_owner = User.objects.create_user(
            username="cons_inactive", password="x", is_active=False
        )
        self.viewer = User.objects.create_user(username="cons_viewer", password="x")
        self.viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        self.stranger = User.objects.create_user(username="cons_stranger", password="x")

        self.compute = Compute.objects.create(
            name="cons-compute", hostname="127.0.0.1:1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="cons-vm",
            uuid="77777777-8888-9999-aaaa-bbbbbbbbbbbb",
        )
        UserInstance.objects.create(instance=self.instance, user=self.owner)
        UserInstance.objects.create(instance=self.instance, user=self.inactive_owner)

    def test_superuser_and_owner_may_open_console(self):
        self.assertTrue(can_open_console(self.superuser, self.instance))
        self.assertTrue(can_open_console(self.owner, self.instance))

    def test_view_instances_stranger_and_inactive_owner_may_not(self):
        self.assertFalse(can_open_console(self.viewer, self.instance))
        self.assertFalse(can_open_console(self.stranger, self.instance))
        self.assertFalse(can_open_console(self.inactive_owner, self.instance))

    def test_owner_can_download_vv_file(self):
        self.client.force_login(self.owner)
        with patch("instances.models.wvmInstance") as wvm:
            proxy = wvm.return_value.cached_reads.return_value.__enter__.return_value
            proxy.instance.name.return_value = "cons-vm"
            proxy.host = "192.0.2.7"
            proxy.get_console_type.return_value = "vnc"
            proxy.get_console_listener_addr.return_value = "0.0.0.0"
            proxy.get_console_port.return_value = "5900"
            proxy.get_console_passwd.return_value = "secret"
            res = self.client.get(reverse("instances:getvvfile", args=[self.instance.id]))
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"[virt-viewer]", res.content)
        # the VM found by its UUID; a console on all addresses is reached through the host
        for line in (b"type=vnc", b"host=192.0.2.7", b"port=5900", b"title=cons-vm"):
            self.assertIn(line + b"\n", res.content)
        # the password only with the permission the console page asks for, as there
        self.assertNotIn(b"password=", res.content)
        self.owner.user_permissions.add(Permission.objects.get(codename="passwordless_console"))
        with patch("instances.models.wvmInstance") as wvm:
            proxy = wvm.return_value.cached_reads.return_value.__enter__.return_value
            proxy.get_console_passwd.return_value = "secret"
            res = self.client.get(reverse("instances:getvvfile", args=[self.instance.id]))
        self.assertIn(b"password=secret\n", res.content)

    def test_owner_can_get_vdi_url(self):
        self.client.force_login(self.owner)
        with patch("datasource.views.wvmInstance", MagicMock()), patch(
            "datasource.views.get_hostname_by_ip", return_value="host"
        ):
            res = self.client.get(
                reverse("vdi_url", args=[self.compute.id, self.instance.name])
            )
        self.assertEqual(res.status_code, 200)
