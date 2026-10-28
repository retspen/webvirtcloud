"""Volume clone runs as a job: the page queues it, the worker copies."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse

from computes.models import Compute
from operations.jobs import Context
from operations.models import Claim, Operation, acquire
from storages.jobs import CloneVolume


class VolumeCloneJobTestCase(TransactionTestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="vol-c", hostname="192.0.2.20", login="root", password="", type=1)
        admin = get_user_model().objects.create_superuser("vol_admin", "a@example.com", "pw")
        self.client.force_login(admin)
        patcher = patch("storages.jobs.wvmStorage")
        self.stg = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.stg.get_volumes.return_value = ["base.qcow2"]
        self.stg.get_volume_format_type.return_value = "qcow2"
        self.stg.clone_name.return_value = "copy.qcow2"
        self.stg.clone_volume.return_value = "copy.qcow2"

    @patch("storages.views.wvmStorage")
    def test_the_page_queues_the_copy_and_the_worker_makes_it(self, page):
        page.return_value.is_active.return_value = False
        page.return_value.get_size.return_value = (1, 1)
        url = reverse("storage", args=[self.compute.pk, "pool-a"])
        response = self.client.post(url, {"cln_volume": "1", "image": "base.qcow2", "name": "copy",
                                          "submission_key": "key-vol00001"})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        op = Operation.objects.get()
        self.assertEqual((op.kind, op.intent["target"]), ("volume.clone", "copy.qcow2"))
        self.assertIn((f"volume:{self.compute.pk}:pool-a/copy.qcow2", "exclusive"),
                      set(Claim.objects.values_list("resource", "mode")))
        self.stg.clone_volume.assert_not_called()

        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        CloneVolume().run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
        op.refresh_from_db()
        self.stg.clone_volume.assert_called_once_with("base.qcow2", "copy", None, False)
        self.assertEqual(op.intent["created"], "copy.qcow2")
        self.assertIn(f"key=pool%3A{self.compute.pk}%3Apool-a", self.client.get(url).content.decode())

    @patch("storages.views.wvmStorage")
    def test_a_refused_copy_is_a_message(self, page):
        # a name in use, an ISO image: the job's plan refuses, the page says why
        page.return_value.is_active.return_value = False
        page.return_value.get_size.return_value = (1, 1)
        url = reverse("storage", args=[self.compute.pk, "pool-a"])
        self.stg.get_volumes.return_value = ["base.qcow2", "copy.qcow2", "install.ISO"]
        for key, image, why in (("key-vol00002", "base.qcow2", "Name of volume already in use"),
                                ("key-vol00003", "install.ISO", "An ISO image is not cloned")):
            with self.subTest(image=image):
                response = self.client.post(url, {"cln_volume": "1", "image": image, "name": "copy",
                                                  "submission_key": key}, follow=True)
                self.assertContains(response, why)
        self.assertFalse(Operation.objects.exists())

    def test_recovery(self):
        self.stg.get_volumes.return_value = ["base.qcow2", "copy.qcow2"]
        op = Operation(params={"compute": self.compute.pk, "pool": "pool-a"}, intent={"target": "copy.qcow2"})
        self.assertEqual(CloneVolume().reconcile(op).state, Operation.UNCERTAIN)  # there, not proven complete
        self.stg.get_volumes.return_value = []
        self.assertEqual(CloneVolume().reconcile(op).state, Operation.FAILED)
        op.intent["created"] = "copy.qcow2"
        self.assertEqual(CloneVolume().reconcile(op).state, Operation.SUCCEEDED)
