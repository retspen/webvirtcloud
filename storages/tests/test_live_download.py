"""Live check of a volume download from the storage page: the bytes are the
volume file's, and a volume a running VM uses is refused. Runs only with
TEST_LIBVIRT_HOST set."""

import os
import unittest

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from vrtManager.connection import connection_manager
from vrtManager.tests import livetest

P = livetest.PREFIX


@unittest.skipUnless(livetest.enabled(), "Set TEST_LIBVIRT_HOST to run the live libvirt tests")
class LiveDownloadTestCase(TestCase):
    def setUp(self):
        args = dict(
            hostname=os.environ["TEST_LIBVIRT_HOST"],
            login=os.environ.get("TEST_LIBVIRT_LOGIN", ""),
            password=os.environ.get("TEST_LIBVIRT_PASSWORD", ""),
            type=int(os.environ.get("TEST_LIBVIRT_TYPE", 1)),
        )
        self.conn = connection_manager.get_connection(*args.values())
        livetest.ensure_pool(self.conn)
        self.addCleanup(livetest.cleanup, self.conn)
        self.compute = Compute.objects.create(name="live-download", **args)
        self.client.force_login(get_user_model().objects.create_superuser("live-dl", "ld@example.com", "x"))

    def download(self, name):
        return self.client.get(reverse("download_volume", args=[self.compute.id, livetest.POOL, name]))

    def test_the_download_is_the_volume_file(self):
        vol = self.conn.storageVolLookupByPath(livetest.create_volume(self.conn, P + "dl", 1, "raw"))
        data = os.urandom(1 << 20)
        stream = self.conn.newStream(0)
        vol.upload(stream, 0, len(data), 0)
        stream.send(data)
        stream.finish()

        response = self.download(P + "dl.raw")
        self.assertEqual(response["Content-Length"], str(len(data)))
        self.assertEqual(response["Content-Disposition"], f'attachment; filename="{P}dl.raw"')
        self.assertEqual(b"".join(response.streaming_content), data)

    def test_a_qcow2_volume_comes_as_its_file(self):
        vol = self.conn.storageVolLookupByPath(livetest.create_volume(self.conn, P + "dl", 64, "qcow2"))
        content = b"".join(self.download(P + "dl.qcow2").streaming_content)
        self.assertEqual(content[:4], b"QFI\xfb")
        self.assertEqual(len(content), vol.infoFlags(1)[2])  # the file, not the 64 MiB the guest sees

    def test_a_running_vm_s_volume_is_refused(self):
        path = livetest.create_volume(self.conn, P + "dl", 64, "qcow2")
        livetest.define_vm(self.conn, P + "dl-vm", [path]).create()
        response = self.download(P + "dl.qcow2")
        self.assertRedirects(response, reverse("storage", args=[self.compute.id, livetest.POOL]),
                             fetch_redirect_response=False)
        self.assertIn("shut them down", str(list(get_messages(response.wsgi_request))[0]))
