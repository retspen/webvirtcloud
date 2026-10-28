"""The pool page and its volume list still answer while a volume is cloned in
the pool (libvirt refuses to refresh it then) and for a pool without a size;
the page measures the pool after refreshing it and says what it cannot show;
a new volume is at least 1 GiB."""

from unittest.mock import call, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from libvirt import libvirtError
from lxml import html

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

    def test_the_pool_is_measured_after_its_refresh(self):
        # update_volumes refreshes the pool: libvirt's space figures are as of the last refresh
        self.conn.get_size.return_value = (10, 4)
        self.client.get(reverse("storage", args=[self.compute.pk, "default"]))
        calls = [c for c in self.conn.mock_calls if c in (call.update_volumes(), call.get_size())]
        self.assertEqual(calls, [call.update_volumes(), call.get_size()])

    def test_a_space_it_cannot_read_is_not_zero(self):
        # the size and the status both read the pool's info: neither failure is a server error
        self.conn.get_size.side_effect = libvirtError("cannot read")
        self.conn.get_status.side_effect = libvirtError("cannot read")
        response = self.client.get(reverse("storage", args=[self.compute.pk, "default"]))
        self.assertContains(response, "The pool's space could not be read.")
        self.assertNotContains(response, "0 bytes")

    def test_a_stopped_pool_says_why_it_lists_no_volumes(self):
        # and loads no search script: the page has no search box for it
        self.conn.is_active.return_value = False
        self.conn.get_size.return_value = (0, 0)
        response = self.client.get(reverse("storage", args=[self.compute.pk, "default"]))
        self.assertContains(response, "This pool is stopped")
        self.assertContains(response, "Unavailable while the pool is stopped.")
        self.assertNotContains(response, "0 bytes")
        self.assertNotContains(response, "table_filter.js")
        self.conn.update_volumes.assert_not_called()

    def test_volumes_are_searched_by_name_and_share_one_clone_dialog(self):
        self.conn.get_size.return_value = (10, 4)
        self.conn.update_volumes.return_value = [
            {"name": name, "size": 1, "allocation": 1, "type": "raw"} for name in ("data.img", "install.iso", "Boot.ISO")]
        page = html.fromstring(self.client.get(reverse("storage", args=[self.compute.pk, "default"])).content)
        self.assertEqual(page.xpath("//tbody/tr/@data-search"), ["data.img", "install.iso", "Boot.ISO"])
        self.assertEqual(len(page.xpath("//div[contains(concat(' ', @class, ' '), ' modal ')][.//button[@name='cln_volume']]")), 1)
        # an ISO image is not cloned, whatever case its name has
        clone = {b.get("data-volume"): b.get("disabled") is None for b in page.xpath("//button[@data-volume]")}
        self.assertEqual(clone, {"data.img": True, "install.iso": False, "Boot.ISO": False})
        self.assertTrue(page.xpath("//div[@id='no-match'][@hidden]"))


class PoolApiTests(TestCase):
    """The API's pool, like the page, is measured after its refresh; a stopped pool lists no volumes."""

    def setUp(self):
        self.compute = Compute.objects.create(name="pa", hostname="192.0.2.24", login="root", password="", type=1)
        self.client.force_login(get_user_model().objects.create_superuser("pa-admin", "pa@example.com", "pw"))
        patcher = patch("storages.api.viewsets.wvmStorage")
        self.conn = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.conn.get_size.return_value = (10, 4)
        self.conn.get_status.return_value = "Running normally"
        self.conn.get_target_path.return_value = "/var/lib/libvirt/images"
        self.conn.get_type.return_value = "dir"
        self.conn.get_autostart.return_value = 1
        self.conn.update_volumes.return_value = []
        self.url = f"/api/v1/computes/{self.compute.id}/storages/default/"

    def test_an_active_pool_is_measured_after_its_refresh(self):
        self.conn.is_active.return_value = True
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        calls = [c for c in self.conn.mock_calls if c in (call.update_volumes(), call.get_size())]
        self.assertEqual(calls, [call.update_volumes(), call.get_size()])

    def test_a_stopped_pool_lists_no_volumes(self):
        self.conn.is_active.return_value = False
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["volumes"])
        self.conn.update_volumes.assert_not_called()
