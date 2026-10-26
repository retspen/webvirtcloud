"""The pool page and its volume list still answer while a volume is cloned in
the pool (libvirt refuses to refresh it then) and for a pool without a size;
a new volume is at least 1 GiB."""

from unittest.mock import patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError

from storages.forms import CreateVolumeForm


class PoolPageTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="pp", hostname="192.0.2.22", login="root", password="", type=1)
        self.client.force_login(get_user_model().objects.create_superuser("pp-admin", "pp@example.com", "pw"))
        patcher = patch("storages.views.wvmStorage")
        self.conn = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.conn.is_active.return_value = True
        self.conn.refresh.side_effect = libvirtError("pool 'default' has asynchronous jobs running.")
        self.conn.get_volumes.return_value = ["base.qcow2"]
        self.conn.update_volumes.return_value = [{"name": "base.qcow2", "size": 1, "allocation": 1, "type": "qcow2"}]

    def test_the_page_answers_while_a_volume_is_cloned(self):
        self.conn.get_size.return_value = (0, 0)  # an iSCSI pool without LUNs
        response = self.client.get(reverse("storage", args=[self.compute.pk, "default"]))
        self.assertContains(response, "base.qcow2")

    def test_the_volume_list_answers_while_a_volume_is_cloned(self):
        response = self.client.get(reverse("volumes", args=[self.compute.pk, "default"]))
        self.assertEqual(response.json(), {"vols": ["base.qcow2"]})

    def test_a_new_volume_has_a_size_in_gib(self):
        form = CreateVolumeForm({"name": "disk1", "format": "qcow2", "size": 0})
        self.assertIn("size", form.errors)
        self.assertIn("Size (GiB)", str(form["size"].label_tag()))
