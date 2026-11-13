from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import RequestFactory, TestCase
from django.urls import reverse

from computes.models import Compute
from operations import claims

User = get_user_model()


class GetVolumesViewTests(TestCase):
    """get_volumes must not answer 200 with an empty list when the pool cannot
    be read: the caller could not tell that apart from a pool with no volumes."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="vols_admin", password="password", email="vols_admin@example.com"
        )
        self.client.login(request=RequestFactory().get("/"), username="vols_admin", password="password")
        self.compute = Compute.objects.create(name="VolCompute", hostname="localhost", type=1, login="u", password="p")
        self.url = reverse("volumes", args=[self.compute.id, "default"])

    @patch("storages.views.wvmStorage")
    def test_listing_failure_is_not_a_200(self, mock_wvm):
        from libvirt import libvirtError

        mock_wvm.return_value.get_volumes.side_effect = libvirtError("pool is gone")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    @patch("storages.views.wvmStorage")
    def test_listing_success_returns_the_volumes(self, mock_wvm):
        mock_wvm.return_value.get_volumes.return_value = ["b.qcow2", "a.qcow2"]
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["vols"], ["a.qcow2", "b.qcow2"])


class PoolPageTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser(username="pool_admin", password="password", email="pool_admin@example.com")
        self.client.login(request=RequestFactory().get("/"), username="pool_admin", password="password")
        self.compute = Compute.objects.create(name="PoolCompute", hostname="localhost", type=1, login="u", password="p")

    @patch("storages.views.wvmStorage")
    def test_a_pool_the_host_does_not_have_goes_back_to_the_pools_with_the_reason(self, mock_wvm):
        from libvirt import libvirtError

        mock_wvm.side_effect = libvirtError("Storage pool not found: no storage pool with matching name 'default'")
        response = self.client.get(reverse("storage", args=[self.compute.id, "default"]))
        self.assertRedirects(response, reverse("storages", args=[self.compute.id]), fetch_redirect_response=False)
        self.assertIn("no storage pool with matching name", str(list(get_messages(response.wsgi_request))[0]))


class VolumeDeleteTests(TestCase):
    """A volume a VM still needs is refused with its reason, on the page and in the API."""

    def setUp(self):
        User.objects.create_superuser(username="vol_admin", password="password", email="vol_admin@example.com")
        self.client.login(request=RequestFactory().get("/"), username="vol_admin", password="password")
        self.compute = Compute.objects.create(name="VolCompute", hostname="localhost", type=1, login="u", password="p")

    def refused(self, mock_wvm):
        from vrtManager import util

        conn = mock_wvm.return_value
        conn.is_active.return_value = False
        conn.get_size.return_value = (1, 1)
        conn.del_volume.side_effect = util.InUse("Volume disk.qcow2 is in use")
        return conn

    @patch("storages.views.wvmStorage")
    def test_the_page_shows_the_refusal(self, mock_wvm):
        conn = self.refused(mock_wvm)
        url = reverse("storage", args=[self.compute.id, "default"])
        response = self.client.post(url, {"del_volume": "1", "volname": "disk.qcow2"})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        conn.del_volume.assert_called_once_with("disk.qcow2")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("disk.qcow2 is in use" in m for m in messages), messages)
        self.assertFalse(any("is deleted" in m for m in messages), messages)

    def test_the_check_and_the_delete_hold_the_compute_lock(self):
        """No VM operation (they share the compute lock) attaches the volume
        between the check and the delete."""
        from contextlib import contextmanager

        held = []

        @contextmanager
        def lock(compute, *args, **kwargs):
            held.append((compute.pk, kwargs.get("shared", False)))
            yield
            held.pop()

        for module, request in (
            ("storages.views", lambda: self.client.post(reverse("storage", args=[self.compute.id, "default"]),
                                                        {"del_volume": "1", "volname": "disk.qcow2"})),
            ("storages.api.viewsets", lambda: self.client.delete(
                f"/api/v1/computes/{self.compute.id}/storages/default/volumes/disk.qcow2/")),
        ):
            with self.subTest(module), patch(f"{module}.wvmStorage") as mock_wvm, \
                    patch(f"{module}.libvirt_compute_lock", lock):
                conn = mock_wvm.return_value
                conn.is_active.return_value = True
                conn.get_size.return_value = (1, 1)
                inside = []
                conn.del_volume.side_effect = lambda name: inside.append(list(held))
                request()
                self.assertEqual(inside, [[(self.compute.pk, False)]])

    def test_the_other_computes_are_asked_before_the_lock(self):
        # shared storage: another host's VM may use the file at the same path;
        # a host that does not answer does not hold this one's lock meanwhile
        for module, request in (
            ("storages.views", lambda: self.client.post(reverse("storage", args=[self.compute.id, "default"]),
                                                        {"del_volume": "1", "volname": "disk.qcow2"})),
            ("storages.api.viewsets", lambda: self.client.delete(
                f"/api/v1/computes/{self.compute.id}/storages/default/volumes/disk.qcow2/")),
        ):
            with self.subTest(module), patch(f"{module}.wvmStorage") as mock_wvm, \
                    patch(f"{module}.libvirt_compute_lock") as lock, \
                    patch(f"{module}.paths_used_on_other_computes", return_value=set()) as others:
                conn = mock_wvm.return_value
                conn.is_active.return_value = True
                conn.get_size.return_value = (1, 1)

                def check(name, elsewhere, lock=lock):
                    lock.assert_not_called()
                    elsewhere(["/pool/disk.qcow2"])

                conn.check_unused_elsewhere.side_effect = check
                request()
                others.assert_called_once_with(self.compute, ["/pool/disk.qcow2"])
                conn.del_volume.assert_called_once_with("disk.qcow2")

    @patch("storages.views.wvmStorage")
    def test_a_busy_compute_is_a_message(self, mock_wvm):
        conn = self.refused(mock_wvm)
        url = reverse("storage", args=[self.compute.id, "default"])
        with patch("storages.views.libvirt_compute_lock", side_effect=claims.Busy("compute:1")):
            response = self.client.post(url, {"del_volume": "1", "volname": "disk.qcow2"})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        conn.del_volume.assert_not_called()
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("short operation" in m for m in messages), messages)

    @patch("storages.api.viewsets.wvmStorage")
    def test_the_api_refuses_with_the_reason(self, mock_wvm):
        conn = self.refused(mock_wvm)
        conn.is_active.return_value = True
        response = self.client.delete(f"/api/v1/computes/{self.compute.id}/storages/default/volumes/disk.qcow2/")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn("disk.qcow2 is in use", response.json()["detail"])

    @patch("storages.api.viewsets.wvmStorage")
    def test_the_api_reads_no_volumes_of_a_stopped_pool(self, mock_wvm):
        # it answered an empty list, or a made-up volume for any name
        mock_wvm.return_value.is_active.return_value = False
        base = f"/api/v1/computes/{self.compute.id}/storages/default/volumes/"
        for url in (base, base + "anything.qcow2/"):
            with self.subTest(url):
                response = self.client.get(url)
                self.assertEqual((response.status_code, response.json()), (409, {"detail": "Pool is not active"}))
