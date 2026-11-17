from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import RequestFactory, TestCase
from django.urls import reverse

from computes.models import Compute
from vmbackups.models import Backup, BackupTarget, BackupTargetPool
from vmbackups.utils import inside_vm_pool
from vrtManager.backup import pool_space, target_pool
from vrtManager.util import OperationError

User = get_user_model()


def pool_mock(name="b1", uuid="aaaaaaaa-0000-4000-8000-000000000001", kind="dir", active=True, path="/srv/b1"):
    pool = MagicMock()
    pool.name.return_value = name
    pool.UUIDString.return_value = uuid
    pool.isActive.return_value = active
    pool.XMLDesc.return_value = f"<pool type='{kind}'><name>{name}</name><target><path>{path}</path></target></pool>"
    pool.info.return_value = [2, 100, 40, 60]
    return pool


class TargetPoolTests(TestCase):
    """vrtManager: which pool a target may use."""

    def conn(self, pool):
        conn = MagicMock()
        conn.get_storage.return_value = pool
        return conn

    def test_an_active_directory_pool_is_taken(self):
        pool = pool_mock()
        self.assertIs(target_pool(self.conn(pool), "b1"), pool)

    def test_a_pool_of_another_type_is_refused(self):
        with self.assertRaisesMessage(OperationError, "b1"):
            target_pool(self.conn(pool_mock(kind="logical")), "b1")

    def test_a_stopped_pool_is_refused(self):
        with self.assertRaises(OperationError):
            target_pool(self.conn(pool_mock(active=False)), "b1")

    def test_a_replaced_pool_is_refused(self):
        with self.assertRaises(OperationError):
            target_pool(self.conn(pool_mock(uuid="bbbbbbbb-0000-4000-8000-000000000002")), "b1", "aaaaaaaa-0000-4000-8000-000000000001")

    def test_a_missing_pool_is_refused(self):
        from libvirt import VIR_ERR_NO_STORAGE_POOL, libvirtError

        error = libvirtError("no pool")
        error.get_error_code = lambda: VIR_ERR_NO_STORAGE_POOL
        conn = MagicMock()
        conn.get_storage.side_effect = error
        with self.assertRaisesMessage(OperationError, "b1"):
            target_pool(conn, "b1")

    def test_pool_space_is_read_after_a_refresh(self):
        pool = pool_mock()
        self.assertEqual(pool_space(pool), {"name": "b1", "size": 100, "free": 60, "used_percent": 40})
        self.assertEqual([call[0] for call in pool.method_calls][:2], ["refresh", "info"])

    def test_inside_a_vm_pool(self):
        conn = MagicMock()
        conn.file_pools.return_value = {"default": (None, "/var/lib/libvirt/images"), "b1": (None, "/var/lib/libvirt/images/b1")}
        self.assertEqual(inside_vm_pool(conn, pool_mock(path="/var/lib/libvirt/images/b1")), "default")
        conn.file_pools.return_value = {"default": (None, "/var/lib/libvirt/images"), "b1": (None, "/srv/b1")}
        self.assertIsNone(inside_vm_pool(conn, pool_mock(path="/srv/b1")))


@patch("vmbackups.views.wvmConnect")
@patch("vmbackups.views.target_pool")
class TargetPageTests(TestCase):
    def setUp(self):
        User.objects.create_superuser(username="bk_admin", password="password", email="bk_admin@example.com")
        self.client.login(request=RequestFactory().get("/"), username="bk_admin", password="password")
        self.c1 = Compute.objects.create(name="h1", hostname="192.0.2.11", login="u", password="p", type=1)
        self.c2 = Compute.objects.create(name="h2", hostname="192.0.2.12", login="u", password="p", type=1)

    def add_target(self):
        target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=target, compute=self.c1, pool="b1", pool_uuid="aaaaaaaa-0000-4000-8000-000000000001")
        return target

    def test_a_target_is_added_with_its_pool_uuid(self, mock_pool, mock_conn):
        mock_pool.return_value = pool_mock()
        response = self.client.post(reverse("vmbackups:target_new"), {"name": "nfs1", "compute": self.c1.id, "pool": "b1"})
        target = BackupTarget.objects.get(name="nfs1")
        self.assertRedirects(response, reverse("vmbackups:target", args=[target.id]), fetch_redirect_response=False)
        row = target.pools.get()
        self.assertEqual((row.compute, row.pool, row.pool_uuid), (self.c1, "b1", "aaaaaaaa-0000-4000-8000-000000000001"))

    def test_a_refused_pool_adds_no_target(self, mock_pool, mock_conn):
        mock_pool.side_effect = OperationError("Storage pool %(pool)s is not usable", pool="b1")
        response = self.client.post(reverse("vmbackups:target_new"), {"name": "nfs1", "compute": self.c1.id, "pool": "b1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Storage pool b1 is not usable")
        self.assertFalse(BackupTarget.objects.exists())

    def test_a_second_compute_pool_must_be_the_same_directory(self, mock_pool, mock_conn):
        target = self.add_target()
        mock_pool.return_value = pool_mock()
        mock_conn.same_directory.return_value = False
        response = self.client.post(reverse("vmbackups:target", args=[target.id]), {"add_pool": "1", "compute": self.c2.id, "pool": "b1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not the same directory")
        self.assertEqual(target.pools.count(), 1)

    def test_a_second_compute_pool_of_the_same_directory_is_added(self, mock_pool, mock_conn):
        target = self.add_target()
        mock_pool.return_value = pool_mock()
        mock_conn.same_directory.return_value = True
        self.client.post(reverse("vmbackups:target", args=[target.id]), {"add_pool": "1", "compute": self.c2.id, "pool": "b1"})
        self.assertEqual(target.pools.count(), 2)

    @patch("vmbackups.views.inside_vm_pool", return_value="default")
    def test_the_page_warns_when_the_target_is_inside_a_vm_pool(self, mock_inside, mock_pool, mock_conn):
        target = self.add_target()
        mock_pool.return_value = pool_mock()
        response = self.client.get(reverse("vmbackups:target", args=[target.id]))
        self.assertContains(response, "inside storage pool default")

    def test_a_pool_with_backups_cannot_be_removed(self, mock_pool, mock_conn):
        target = self.add_target()
        Backup.objects.create(target=target, vm_uuid="u", vm_name="vm1", compute_name="h1")
        url = reverse("vmbackups:target", args=[target.id])
        response = self.client.post(url, {"remove_pool": target.pools.get().id})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertEqual(target.pools.count(), 1)
        response = self.client.post(url, {"delete": "1"})
        self.assertTrue(BackupTarget.objects.filter(pk=target.pk).exists())

    def test_an_empty_target_is_deleted(self, mock_pool, mock_conn):
        target = self.add_target()
        response = self.client.post(reverse("vmbackups:target", args=[target.id]), {"delete": "1"})
        self.assertRedirects(response, reverse("vmbackups:targets"), fetch_redirect_response=False)
        self.assertFalse(BackupTarget.objects.exists())

    def test_only_superusers(self, mock_pool, mock_conn):
        target = self.add_target()
        User.objects.create_user(username="owner", password="password")
        self.client.logout()
        self.client.login(request=RequestFactory().get("/"), username="owner", password="password")
        self.assertEqual(self.client.get(reverse("vmbackups:targets")).status_code, 403)
        self.assertEqual(self.client.get(reverse("vmbackups:target", args=[target.id])).status_code, 403)


class StorageRefusalTests(TestCase):
    def setUp(self):
        User.objects.create_superuser(username="st_admin", password="password", email="st_admin@example.com")
        self.client.login(request=RequestFactory().get("/"), username="st_admin", password="password")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.11", login="u", password="p", type=1)
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u1")
        self.backup = Backup.objects.create(target=self.target, vm_uuid="u", vm_name="vm1", compute_name="h1")
        self.url = reverse("storage", args=[self.compute.id, "b1"])

    @patch("storages.views.wvmStorage")
    def test_a_backup_volume_is_not_deleted_from_the_storage_page(self, mock_wvm):
        conn = mock_wvm.return_value
        response = self.client.post(self.url, {"del_volume": "1", "volname": f"{self.backup.prefix}-vda.qcow2"})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        conn.del_volume.assert_not_called()
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("belongs to a backup of vm1" in m for m in messages), messages)

    @patch("storages.views.wvmStorage")
    def test_another_volume_of_the_target_pool_is_deleted(self, mock_wvm):
        conn = mock_wvm.return_value
        conn.check_unused_elsewhere.return_value = None
        self.client.post(self.url, {"del_volume": "1", "volname": "wvc-00000000-0000-4000-8000-000000000009-vda.qcow2"})
        conn.del_volume.assert_called_once()

    @patch("storages.views.wvmStorage")
    def test_a_target_pool_is_not_deleted_from_the_storage_page(self, mock_wvm):
        conn = mock_wvm.return_value
        response = self.client.post(self.url, {"delete": "1"})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        conn.delete.assert_not_called()
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("is backup target nfs1" in m for m in messages), messages)

    @patch("storages.api.viewsets.wvmStorage")
    def test_the_api_does_not_delete_a_backup_volume(self, mock_wvm):
        mock_wvm.return_value.is_active.return_value = True
        response = self.client.delete(f"/api/v1/computes/{self.compute.id}/storages/b1/volumes/{self.backup.prefix}-vda.qcow2/")
        self.assertEqual(response.status_code, 409)
        mock_wvm.return_value.del_volume.assert_not_called()
