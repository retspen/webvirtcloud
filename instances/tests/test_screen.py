"""The VM's screen on its page: a PNG from libvirt (virDomainScreenshot), for those who may open its console."""
from unittest.mock import MagicMock, PropertyMock, patch

import libvirt
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance
from vrtManager.instance import wvmInstance

PNG = b"\x89PNG\r\n\x1a\nimage"


class ScreenTestCase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("sc-admin", "sc@example.com", "pw")
        compute = Compute.objects.create(name="sc-host", hostname="192.0.2.91", login="", password="", type=4)
        self.vm = Instance.objects.create(compute=compute, name="sc-vm", uuid="91919191-0000-4000-8000-000000000001")
        self.proxy = MagicMock(**{"screenshot.return_value": ("image/png", PNG)})
        patch.object(Instance, "proxy", property(lambda vm: self.proxy)).start()
        self.status = patch.object(Instance, "status", new_callable=PropertyMock, return_value=1).start()
        self.console = patch.object(Instance, "console_type", new_callable=PropertyMock, return_value="vnc").start()
        self.addCleanup(patch.stopall)

    def get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("instances:screen", args=[self.vm.pk]))

    def test_a_running_vm_s_screen_is_a_png_not_kept_by_the_browser(self):
        response = self.get(self.admin)
        self.assertEqual((response.status_code, response["Content-Type"], response.content), (200, "image/png", PNG))
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_only_those_who_may_open_the_console_see_it(self):
        viewer = get_user_model().objects.create_user("sc-viewer", "v@example.com", "pw")
        viewer.user_permissions.add(Permission.objects.get(codename="view_instances"))
        self.assertEqual(self.get(viewer).status_code, 403)  # reads every VM, opens no console
        owner = get_user_model().objects.create_user("sc-owner", "o@example.com", "pw")
        UserInstance.objects.create(user=owner, instance=self.vm)
        self.assertEqual(self.get(owner).status_code, 200)

    def test_no_screen_is_a_404(self):
        for status, console, answer in ((5, "vnc", None), (1, "", None), (1, "vnc", ("image/x-portable-pixmap", b"P6")),
                                        (1, "vnc", libvirt.libvirtError("no screen"))):
            with self.subTest(status=status, console=console, answer=answer):
                self.status.return_value, self.console.return_value = status, console
                self.proxy.screenshot.side_effect = [answer] if answer else None
                self.assertEqual(self.get(self.admin).status_code, 404)


class ScreenshotCallTestCase(TestCase):
    def test_the_stream_is_read_whole_and_aborted_on_failure(self):
        proxy = MagicMock()
        stream = proxy.wvm.newStream.return_value
        proxy.instance.screenshot.return_value = "image/png"
        stream.recvAll.side_effect = lambda handler, buffer: [handler(stream, part, buffer) for part in (b"ab", b"cd")]
        self.assertEqual(wvmInstance.screenshot(proxy), ("image/png", b"abcd"))
        stream.finish.assert_called_once_with()
        proxy.instance.screenshot.side_effect = libvirt.libvirtError("gone")
        with self.assertRaises(libvirt.libvirtError):
            wvmInstance.screenshot(proxy)
        stream.abort.assert_called_once_with()
