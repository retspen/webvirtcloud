"""A volume download streams what the host reads, as a file; a refusal is a
message on the storage page; only a superuser downloads."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from computes.models import Compute
from vrtManager.util import OperationError


class DownloadTestCase(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="dl", hostname="192.0.2.30", login="root", password="", type=1)
        self.url = reverse("download_volume", args=[self.compute.id, "pool-a", "disk.qcow2"])
        patcher = patch("storages.views.wvmStorage")
        self.stg = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.client.force_login(get_user_model().objects.create_superuser("dl_admin", "a@example.com", "pw"))

    def test_the_volume_comes_as_a_file(self):
        self.stg.read_volume.return_value = (3, iter([b"ab", b"c"]))
        with patch("storages.views.request_progressed") as progressed:
            response = self.client.get(self.url)
            self.assertEqual(b"".join(response.streaming_content), b"abc")
        self.assertEqual(progressed.call_count, 2)
        self.assertEqual((response["Content-Length"], response["Content-Disposition"], response["X-Accel-Buffering"]),
                         ("3", 'attachment; filename="disk.qcow2"', "no"))
        self.stg.read_volume.assert_called_once_with("disk.qcow2")

    def test_a_refusal_is_a_message_on_the_storage_page(self):
        self.stg.read_volume.side_effect = OperationError("The running VMs %(vms)s use volume %(name)s; shut them down to copy it",
                                                          vms="vm1", name="disk.qcow2")
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("storage", args=[self.compute.id, "pool-a"]), fetch_redirect_response=False)
        self.assertIn("shut them down", str(list(get_messages(response.wsgi_request))[0]))

    def test_only_a_superuser_downloads(self):
        self.client.force_login(get_user_model().objects.create_user("dl_user", password="pw"))
        self.assertNotEqual(self.client.get(self.url).status_code, 200)
        self.stg.read_volume.assert_not_called()
