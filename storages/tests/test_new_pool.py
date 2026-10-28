"""The new pool dialog: each type needs its own fields, a pool takes no name or
path another one has, an RBD pool only a Ceph secret of the host; a refused
pool opens the dialog again with what was entered and why."""

from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from libvirt import VIR_SECRET_USAGE_TYPE_CEPH, VIR_SECRET_USAGE_TYPE_VOLUME, libvirtError
from lxml import html

from storages.forms import AddStgPool

POOLS = [
    {"name": "default", "type": "dir", "path": "/var/lib/libvirt/images"},
    {"name": "ceph-vms", "type": "rbd", "path": "vms"},  # an RBD pool's path is its Ceph pool
]
SECRET = "00000000-0000-0000-0000-000000000001"


def errors(data):
    form = AddStgPool(data, pools=POOLS, ceph_secrets=[SECRET])
    form.is_valid()
    return sorted(form.errors)


class FormTests(SimpleTestCase):
    def test_each_type_needs_its_fields(self):
        for stg_type, needed in (
            ("dir", ["target"]),
            ("logical", ["erase_device", "source"]),
            ("rbd", ["ceph_host", "ceph_pool", "ceph_user", "secret"]),
            ("netfs", ["netfs_host", "source", "target"]),
        ):
            with self.subTest(stg_type=stg_type):
                self.assertEqual(errors({"name": "new", "stg_type": stg_type}), needed)

    def test_a_pool_takes_no_name_or_path_of_another(self):
        self.assertEqual(errors({"name": "default", "stg_type": "dir", "target": "/srv/new"}), ["name"])
        self.assertEqual(errors({"name": "new", "stg_type": "dir", "target": "/var/lib/libvirt/images/"}), ["target"])
        self.assertEqual(errors({"name": "new", "stg_type": "dir", "target": "vms"}), [])  # not a directory
        self.assertEqual(errors({"name": "..", "stg_type": "dir", "target": "/srv/new"}), ["name"])

    def test_an_rbd_pool_takes_a_ceph_secret_of_the_host(self):
        data = {"name": "new", "stg_type": "rbd", "ceph_host": "mon0.example.com", "ceph_pool": "vms", "ceph_user": "libvirt"}
        self.assertEqual(errors({**data, "secret": SECRET}), [])
        self.assertEqual(errors({**data, "secret": "00000000-0000-0000-0000-000000000002"}), ["secret"])

    def test_an_lvm_pool_is_agreed_to_erase_its_device(self):
        data = {"name": "vg-new", "stg_type": "logical", "source": "/dev/vdb"}
        self.assertEqual(errors(data), ["erase_device"])
        self.assertEqual(errors({**data, "erase_device": "true"}), [])


class DialogTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="np", hostname="192.0.2.25", login="root", password="", type=1)
        self.client.force_login(get_user_model().objects.create_superuser("np-admin", "np@example.com", "pw"))
        patcher = patch("storages.views.wvmStorages")
        self.conn = patcher.start().return_value
        self.addCleanup(patcher.stop)
        pools = [{**pool, "status": 1, "autostart": 1, "volumes": 0, "size": 1, "free": 1, "used_percent": 0} for pool in POOLS]
        self.conn.get_storages_info.return_value = pools
        secrets = {SECRET: (VIR_SECRET_USAGE_TYPE_CEPH, "client.libvirt"),
                   "00000000-0000-0000-0000-000000000003": (VIR_SECRET_USAGE_TYPE_VOLUME, "/var/lib/libvirt/images/a.img")}
        self.conn.get_secrets.return_value = list(secrets)
        self.conn.get_secret.side_effect = lambda uuid: MagicMock(**{"usageType.return_value": secrets[uuid][0],
                                                                    "usageID.return_value": secrets[uuid][1]})
        self.url = reverse("storages", args=[self.compute.pk])

    def page(self, response):
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def test_only_ceph_secrets_are_offered_by_their_names(self):
        page = self.page(self.client.get(self.url))
        self.assertEqual(page.xpath("//select[@name='secret']/option/text()"), ["Choose…", "client.libvirt"])
        self.assertIsNone(page.get_element_by_id("AddStgPool").get("data-open"))

    def test_an_iso_pool_on_the_host_is_linked_not_offered(self):
        self.assertTrue(self.page(self.client.get(self.url)).xpath("//input[@name='pool_kind'][@value='iso']"))
        self.conn.get_storages_info.return_value += [{"name": "iso", "type": "dir", "path": "/srv/iso", "status": 1,
                                                       "autostart": 1, "volumes": 0, "size": 1, "free": 1, "used_percent": 0}]
        page = self.page(self.client.get(self.url))
        self.assertFalse(page.xpath("//input[@name='pool_kind'][@value='iso']"))
        self.assertTrue(page.xpath(f"//div[@id='AddStgPool']//a[@href='{reverse('storage', args=[self.compute.pk, 'iso'])}']"))

    def test_a_refused_pool_opens_the_dialog_again_with_what_was_entered(self):
        page = self.page(self.client.post(self.url, {"create": "1", "pool_kind": "netfs", "stg_type": "netfs",
                                                     "name": "share", "netfs_host": "nfs.example.com",
                                                     "source": "/export", "target": "/var/lib/libvirt/images"}))
        self.conn.create_storage_netfs.assert_not_called()
        self.assertIsNotNone(page.get_element_by_id("AddStgPool").get("data-open"))
        self.assertEqual(page.xpath("//input[@name='pool_kind'][@checked]/@value"), ["netfs"])
        self.assertEqual(page.get_element_by_id("pool_netfs_host").get("value"), "nfs.example.com")
        target = page.get_element_by_id("pool_netfs_target")
        self.assertEqual(target.get("aria-invalid"), "true")
        self.assertIn("Pool default uses this path", page.get_element_by_id("pool_netfs_target_error").text_content())

    def test_a_refused_type_keeps_its_values_to_itself(self):
        # target and source are fields of several types: the others keep their own defaults
        page = self.page(self.client.post(self.url, {"create": "1", "pool_kind": "netfs", "stg_type": "netfs",
                                                     "name": "share", "netfs_host": "nfs.example.com",
                                                     "source": "/export", "target": "/var/lib/libvirt/images"}))
        self.assertEqual(page.get_element_by_id("pool_netfs_source").get("value"), "/export")
        self.assertIsNone(page.get_element_by_id("pool_lvm_source").get("value") or None)
        self.assertIsNone(page.get_element_by_id("pool_dir_target").get("aria-invalid"))
        self.assertEqual(page.get_element_by_id("pool_iso_target").get("value"), "/var/lib/libvirt/iso")

    def test_an_lvm_pool_refused_for_its_acknowledgement_says_so_beside_it(self):
        page = self.page(self.client.post(self.url, {"create": "1", "pool_kind": "logical", "stg_type": "logical",
                                                     "name": "vg-new", "source": "/dev/vdb"}))
        self.conn.create_storage.assert_not_called()
        self.assertEqual(page.get_element_by_id("pool_lvm_erase").get("aria-invalid"), "true")
        self.assertTrue(page.get_element_by_id("pool_lvm_erase_error").text_content())

    def test_a_pool_libvirt_refuses_says_why_in_the_dialog(self):
        self.conn.create_storage.side_effect = libvirtError("cannot create directory '/srv/new': Permission denied")
        page = self.page(self.client.post(self.url, {"create": "1", "pool_kind": "dir", "stg_type": "dir",
                                                     "name": "new", "target": "/srv/new"}))
        self.assertIn("Permission denied", page.xpath("string(//div[@id='AddStgPool']//div[contains(@class,'form-errors')])"))

    def test_a_pool_made(self):
        response = self.client.post(self.url, {"create": "1", "pool_kind": "iso", "stg_type": "dir",
                                               "name": "iso", "target": "/var/lib/libvirt/iso"})
        self.assertRedirects(response, reverse("storage", args=[self.compute.pk, "iso"]), fetch_redirect_response=False)
        self.conn.create_storage.assert_called_once_with("dir", "iso", "", "/var/lib/libvirt/iso")
