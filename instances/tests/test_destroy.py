from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from computes.models import Compute
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from instances.models import Instance
from libvirt import VIR_DOMAIN_UNDEFINE_KEEP_NVRAM, VIR_DOMAIN_UNDEFINE_NVRAM, libvirtError
from vrtManager.util import OperationError


class DestroyOrderTestCase(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("destroy_admin", "d@example.com", "pw")
        self.client.force_login(admin)
        self.client.raise_request_exception = False
        compute = Compute.objects.create(name="destroy-compute", hostname="127.0.0.1", login="", password="", type=4)
        self.instance = Instance.objects.create(
            compute=compute, name="destroy-vm", uuid="11111111-2222-3333-4444-555555555555"
        )

    def destroy(self, undefine_error=None, data=None):
        with patch("instances.models.wvmInstance") as wvm:
            proxy = wvm.return_value
            proxy.instance.isActive.return_value = False
            proxy.split_disk_paths_by_use.return_value = (["/pool/own.qcow2"], ["/pool/shared.qcow2"])
            proxy.delete.side_effect = undefine_error
            self.client.post(reverse("instances:destroy", args=[self.instance.id]), data or {"delete_disk": "1"})
        return proxy

    def test_the_nvram_goes_only_when_asked(self):
        for data, wanted, unwanted in (
            ({"delete_nvram": "1"}, VIR_DOMAIN_UNDEFINE_NVRAM, VIR_DOMAIN_UNDEFINE_KEEP_NVRAM),
            ({}, VIR_DOMAIN_UNDEFINE_KEEP_NVRAM, VIR_DOMAIN_UNDEFINE_NVRAM),
        ):
            with self.subTest(data=data):
                Instance.objects.get_or_create(
                    compute=self.instance.compute, name="destroy-vm", uuid="11111111-2222-3333-4444-555555555555"
                )
                self.instance = Instance.objects.get(uuid="11111111-2222-3333-4444-555555555555")
                flags = self.destroy(data=data).delete.call_args[0][0]
                self.assertTrue(flags & wanted)
                self.assertFalse(flags & unwanted)

    def test_the_api_takes_its_options_as_booleans(self):
        url = f"/api/v1/computes/{self.instance.compute_id}/instances/{self.instance.id}/"
        for body, content_type, deleted in (
            ({"delete_disk": True}, "application/json", True),
            ("delete_disk=false", "application/x-www-form-urlencoded", False),
        ):
            with self.subTest(body=body):
                Instance.objects.get_or_create(
                    compute=self.instance.compute, name="destroy-vm", uuid="11111111-2222-3333-4444-555555555555"
                )
                self.instance = Instance.objects.get(uuid="11111111-2222-3333-4444-555555555555")
                with patch("instances.models.wvmInstance") as wvm:
                    proxy = wvm.return_value
                    proxy.instance.isActive.return_value = False
                    proxy.split_disk_paths_by_use.return_value = (["/pool/own.qcow2"], [])
                    url = f"/api/v1/computes/{self.instance.compute_id}/instances/{self.instance.id}/"
                    response = self.client.delete(url, body, content_type=content_type)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(proxy.get_volume_by_path.called, deleted)

    def test_a_disk_file_that_stays_keeps_the_files_it_needs(self):
        # the overlay is not deleted: the file below it would leave it broken
        volumes = {}

        def volume(path):
            vol = volumes.setdefault(path, MagicMock())
            if path == "/pool/vm.snap1":
                vol.delete.side_effect = libvirtError("Permission denied")
            return vol

        with patch("instances.models.wvmInstance") as wvm:
            proxy = wvm.return_value
            proxy.instance.isActive.return_value = False
            proxy.split_disk_paths_by_use.return_value = (["/pool/vm.snap1", "/pool/vm.qcow2", "/pool/vm-data.qcow2"], [])
            proxy.get_volume_by_path.side_effect = volume
            proxy.backing_path.side_effect = {"/pool/vm.snap1": "/pool/vm.qcow2"}.get
            response = self.client.post(reverse("instances:destroy", args=[self.instance.id]), {"delete_disk": "true"})
        self.assertNotIn("/pool/vm.qcow2", volumes)
        volumes["/pool/vm-data.qcow2"].delete.assert_called_once_with(0)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)][-1],
                         "Disk /pool/vm.qcow2 was kept: a disk file that stays needs it")

    def test_when_the_files_a_kept_one_needs_are_unknown_none_of_the_rest_goes(self):
        with patch("instances.models.wvmInstance") as wvm:
            proxy = wvm.return_value
            proxy.instance.isActive.return_value = False
            proxy.split_disk_paths_by_use.return_value = (["/pool/a.qcow2", "/pool/b.qcow2"], [])
            proxy.get_volume_by_path.return_value.delete.side_effect = libvirtError("Permission denied")
            proxy.backing_path.side_effect = libvirtError("pool unreachable")
            response = self.client.post(reverse("instances:destroy", args=[self.instance.id]), {"delete_disk": "true"})
        self.assertEqual(response.status_code, 302)
        proxy.get_volume_by_path.assert_called_once_with("/pool/a.qcow2")

    def test_disks_are_deleted_after_the_undefine(self):
        proxy = self.destroy()
        proxy.get_volume_by_path.assert_called_once_with("/pool/own.qcow2")
        self.assertFalse(Instance.objects.filter(pk=self.instance.pk).exists())

    def test_failed_undefine_deletes_no_disk(self):
        proxy = self.destroy(undefine_error=libvirtError("refused"))
        proxy.get_volume_by_path.assert_not_called()
        self.assertTrue(Instance.objects.filter(pk=self.instance.pk).exists())

    def test_destroy_and_delete_vol_hold_the_compute_exclusively(self):
        calls = []

        @contextmanager
        def record(compute, *, shared=False):
            calls.append(shared)
            yield

        with patch("instances.views.libvirt_compute_lock", record):
            with patch("instances.models.wvmInstance"):
                self.client.post(reverse("instances:delete_vol", args=[self.instance.id]), {"dev": "vda"})
            self.destroy()
        self.assertEqual(calls, [False, False])

    def test_a_volume_the_vms_snapshots_need_is_kept_after_the_detach(self):
        disk = {"dev": "vdb", "path": "/pool/data.qcow2", "storage": "default", "image": "data.qcow2"}
        with patch("instances.models.wvmInstance") as wvm, patch("instances.views.wvmStorage") as storage:
            proxy = wvm.return_value
            proxy.get_disk_devices.return_value = [disk]
            proxy.paths_used_by_other_domains.return_value = set()
            proxy.wait_disk_detached.return_value = True
            storage.return_value.del_volume.side_effect = OperationError("Volume data.qcow2 is in use")
            response = self.client.post(reverse("instances:delete_vol", args=[self.instance.id]), {"dev": "vdb"})
        self.assertEqual(response.status_code, 302)
        proxy.detach_disk.assert_called_once_with("vdb")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("data.qcow2 is in use" in m and "detached" in m for m in messages), messages)

    def test_confirmation_page_takes_no_lock(self):
        calls = []

        @contextmanager
        def record(compute, *, shared=False):
            calls.append(shared)
            yield

        with patch("instances.views.libvirt_compute_lock", record), patch("instances.models.wvmInstance"):
            response = self.client.get(reverse("instances:destroy", args=[self.instance.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [])

    def test_the_confirmation_page_of_a_paused_vm_offers_the_form(self):
        with patch("instances.models.wvmInstance") as wvm:
            wvm.return_value.get_status.return_value = 3  # paused
            response = self.client.get(reverse("instances:destroy", args=[self.instance.id]))
        self.assertIn('id="delete_form"', response.content.decode())
