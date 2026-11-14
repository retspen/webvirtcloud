"""
Disk and media mutation views must be superuser-only (matching the UI, where
the Disk tab is only rendered for superusers), and even for superusers the
views must not act on volumes or option values taken blindly from the client.
"""
from unittest.mock import ANY, patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserInstance
from computes.models import Compute
from instances.models import Instance

DISK_ENDPOINTS = [
    ("add_new_vol", []),
    ("add_existing_vol", []),
    ("edit_volume", []),
    ("delete_vol", []),
    ("detach_vol", []),
    ("add_cdrom", []),
    ("detach_cdrom", ["hda"]),
    ("mount_iso", []),
    ("unmount_iso", []),
    ("refresh_iso", []),
]

VM_DISK = {
    "dev": "vda",
    "bus": "virtio",
    "image": "vm-disk.qcow2",
    "storage": "default",
    "path": "/var/lib/libvirt/images/vm-disk.qcow2",
    "format": "qcow2",
}


class DiskViewsTenantIsolationTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="disk_super", email="disk_super@example.com", password="password"
        )
        self.change_user = User.objects.create_user(
            username="disk_change_user", password="password"
        )
        self.staff_change_user = User.objects.create_user(
            username="disk_staff_change_user", password="password", is_staff=True
        )
        self.compute = Compute.objects.create(
            name="disk-compute", hostname="127.0.0.1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="disk-test-vm",
            uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        for user in (self.change_user, self.staff_change_user):
            UserInstance.objects.create(
                instance=self.instance, user=user, is_change=True, is_delete=False
            )
        self.referer = f"/instances/{self.instance.id}/"

    def _url(self, name, extra=()):
        return reverse(f"instances:{name}", args=[self.instance.id, *extra])

    def _post(self, name, data, extra=()):
        return self.client.post(self._url(name, extra), data, HTTP_REFERER=self.referer)

    def test_owner_with_is_change_cannot_mutate_disks(self):
        for user in (self.change_user, self.staff_change_user):
            self.client.force_login(user)
            with patch("instances.models.wvmInstance") as mock_wvm, patch(
                "instances.views.wvmStorage"
            ) as mock_storage, patch("instances.views.wvmCreate") as mock_create:
                for name, extra in DISK_ENDPOINTS:
                    res = self._post(
                        name,
                        {"storage": "default", "name": "victim.qcow2", "dev": "vda"},
                        extra,
                    )
                    self.assertEqual(
                        res.status_code, 403, f"{user.username} POST {name} should be 403"
                    )
                mock_wvm.assert_not_called()
                mock_storage.assert_not_called()
                mock_create.assert_not_called()

    def test_refresh_iso_reads_the_pools_again_and_returns_to_the_disks_tab(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm:
            mock_wvm.return_value.refresh_iso_pools.return_value = {}
            res = self._post("refresh_iso", {})
        self.assertRedirects(res, self.referer + "#disks", fetch_redirect_response=False)
        mock_wvm.return_value.refresh_iso_pools.assert_called_once_with()

    def test_refresh_iso_reports_the_pools_that_failed(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm:
            mock_wvm.return_value.refresh_iso_pools.return_value = {"busy": "pool is busy"}
            res = self._post("refresh_iso", {})
        self.assertEqual([str(m) for m in get_messages(res.wsgi_request)], ["Pool busy was not read again: pool is busy"])

    def test_delete_vol_deletes_the_volume_attached_to_dev_not_the_posted_one(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmStorage"
        ) as mock_storage:
            mock_wvm.return_value.get_disk_devices.return_value = [VM_DISK]
            mock_wvm.return_value.get_managed_save_image.return_value = 0
            res = self._post(
                "delete_vol",
                {"storage": "other-pool", "name": "victim.qcow2", "dev": "vda", "path": VM_DISK["path"]},
            )
        self.assertEqual(res.status_code, 302)
        mock_wvm.return_value.detach_disk.assert_called_once_with("vda")
        self.assertEqual(mock_storage.call_args[0][-1], "default")
        mock_storage.return_value.del_volume.assert_called_once_with("vm-disk.qcow2")
        mock_storage.return_value.check_unused_elsewhere.assert_called_once_with("vm-disk.qcow2", ANY)

    def test_delete_vol_of_a_volume_another_compute_uses_keeps_the_disk_attached(self):
        from vrtManager.util import InUse

        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmStorage"
        ) as mock_storage:
            mock_wvm.return_value.get_disk_devices.return_value = [VM_DISK]
            mock_wvm.return_value.get_managed_save_image.return_value = 0
            mock_storage.return_value.check_unused_elsewhere.side_effect = InUse("in use on another compute")
            res = self._post("delete_vol", {"dev": "vda", "path": VM_DISK["path"]})
        self.assertEqual([str(m) for m in get_messages(res.wsgi_request)], ["in use on another compute"])
        mock_wvm.return_value.detach_disk.assert_not_called()
        mock_storage.return_value.del_volume.assert_not_called()

    def test_delete_vol_refuses_dev_not_attached_to_vm(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmStorage"
        ) as mock_storage:
            mock_wvm.return_value.get_disk_devices.return_value = [VM_DISK]
            res = self._post(
                "delete_vol",
                {"storage": "default", "name": "victim.qcow2", "dev": "vdz"},
            )
        self.assertEqual(res.status_code, 302)
        mock_wvm.return_value.detach_disk.assert_not_called()
        mock_storage.return_value.del_volume.assert_not_called()

    def test_edit_volume_rejects_unknown_cache_mode(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm:
            proxy = mock_wvm.return_value
            proxy.get_disk_devices.return_value = [VM_DISK]
            proxy.get_media_devices.return_value = []
            proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            proxy.get_cache_modes.return_value = {"default": "", "none": ""}
            proxy.get_io_modes.return_value = {"default": "", "native": ""}
            proxy.get_discard_modes.return_value = {"default": "", "unmap": ""}
            proxy.get_detect_zeroes_modes.return_value = {"default": "", "on": ""}
            res = self._post(
                "edit_volume",
                {
                    "edit_volume": "1",
                    "dev": "vda",
                    "path": VM_DISK["path"],
                    "vol_path": VM_DISK["path"],
                    "vol_bus_old": "virtio",
                    "vol_bus": "virtio",
                    "vol_format": "qcow2",
                    "vol_cache": "none' io='native",
                },
            )
        self.assertEqual(res.status_code, 302)
        proxy.edit_disk.assert_not_called()
        proxy.attach_disk.assert_not_called()
        proxy.detach_disk.assert_not_called()

    def test_add_new_vol_rejects_unknown_bus(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmCreate"
        ) as mock_create, patch("instances.views.wvmStorage"):
            proxy = mock_wvm.return_value
            proxy.get_disk_devices.return_value = [VM_DISK]
            proxy.get_media_devices.return_value = []
            proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            proxy.get_cache_modes.return_value = {"default": "", "none": ""}
            res = self._post(
                "add_new_vol",
                {
                    "storage": "default",
                    "name": "new-disk",
                    "format": "qcow2",
                    "size": "10",
                    "bus": "virtio'/><disk",
                    "cache": "default",
                },
            )
        self.assertEqual(res.status_code, 302)
        mock_create.return_value.create_volume.assert_not_called()
        proxy.attach_disk.assert_not_called()

    def test_add_existing_vol_rejects_volume_not_in_pool(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmStorage"
        ) as mock_storage:
            proxy = mock_wvm.return_value
            proxy.get_disk_devices.return_value = [VM_DISK]
            proxy.get_media_devices.return_value = []
            proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            proxy.get_cache_modes.return_value = {"default": "", "none": ""}
            mock_storage.return_value.get_volumes.return_value = ["vm-disk.qcow2"]
            res = self._post(
                "add_existing_vol",
                {
                    "selected_storage": "default",
                    "vols": "../../../etc/shadow",
                    "bus": "virtio",
                    "cache": "default",
                },
            )
        self.assertEqual(res.status_code, 302)
        proxy.attach_disk.assert_not_called()

    def test_add_existing_vol_attaches_the_volume_by_its_own_path(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmStorage"
        ) as mock_storage:
            proxy = mock_wvm.return_value
            proxy.get_disk_devices.return_value = [VM_DISK]
            proxy.get_media_devices.return_value = []
            proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
            proxy.get_cache_modes.return_value = {"default": "", "none": ""}
            pool = mock_storage.return_value
            pool.get_volumes.return_value = ["unit:0:0:1"]
            pool.get_type.return_value = "iscsi"
            pool.get_volume_type.return_value = "block"
            pool.get_volume_format_type.return_value = None  # an iSCSI pool knows no format
            pool.get_target_path.return_value = "/dev/disk/by-path"
            pool.get_volume.return_value.path.return_value = "/dev/disk/by-path/ip-192.0.2.1:3260-iscsi-iqn.example-lun-1"
            res = self._post(
                "add_existing_vol",
                {"selected_storage": "iscsi", "vols": "unit:0:0:1", "bus": "virtio", "cache": "default"},
            )
        self.assertEqual(res.status_code, 302)
        pool.get_volume.assert_called_once_with("unit:0:0:1")
        self.assertEqual(
            proxy.attach_disk.call_args.args[1], "/dev/disk/by-path/ip-192.0.2.1:3260-iscsi-iqn.example-lun-1"
        )
        self.assertEqual(proxy.attach_disk.call_args.kwargs["format_type"], "raw")

    def _mock_disk_options(self, proxy):
        proxy.get_disk_devices.return_value = [VM_DISK]
        proxy.get_media_devices.return_value = []
        proxy.get_disk_bus_types.return_value = ["virtio", "sata", "scsi"]
        proxy.get_cache_modes.return_value = {"default": "", "none": ""}
        proxy.get_io_modes.return_value = {"default": "", "native": ""}
        proxy.get_discard_modes.return_value = {"default": "", "unmap": ""}
        proxy.get_detect_zeroes_modes.return_value = {"default": "", "on": ""}

    def test_add_new_vol_rejects_unsafe_volume_name(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmCreate"
        ) as mock_create, patch("instances.views.wvmStorage"):
            self._mock_disk_options(mock_wvm.return_value)
            res = self._post(
                "add_new_vol",
                {
                    "storage": "default",
                    "name": "x</name><key>/etc/shadow",
                    "format": "qcow2",
                    "size": "10",
                    "bus": "virtio",
                    "cache": "default",
                },
            )
        self.assertEqual(res.status_code, 302)
        mock_create.return_value.create_volume.assert_not_called()

    def test_edit_volume_accepts_valid_options(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm:
            proxy = mock_wvm.return_value
            self._mock_disk_options(proxy)
            res = self._post(
                "edit_volume",
                {
                    "edit_volume": "1",
                    "dev": "vda",
                    "path": VM_DISK["path"],
                    "vol_path": VM_DISK["path"],
                    "vol_bus_old": "virtio",
                    "vol_bus": "virtio",
                    "vol_format": "qcow2",
                    "vol_serial": "SER-01",
                    "vol_cache": "none",
                    "vol_io_mode": "native",
                    "vol_discard_mode": "unmap",
                    "vol_detect_zeroes": "on",
                },
            )
        self.assertEqual(res.status_code, 302)
        proxy.edit_disk.assert_called_once_with(
            "vda", VM_DISK["path"], False, False, "virtio", "SER-01", "qcow2",
            "none", "native", "unmap", "on",
        )

    def _edit_volume_post(self, **extra):
        data = {
            "edit_volume": "1",
            "dev": "vda",
            "path": VM_DISK["path"],
            "vol_path": VM_DISK["path"],
            "vol_bus_old": "virtio",
            "vol_bus": "virtio",
            "vol_format": "qcow2",
            "vol_cache": "none",
        }
        data.update(extra)
        return self._post("edit_volume", data)

    def test_a_form_of_a_disk_replaced_since_changes_nothing(self):
        # another tab moved vda to another volume after this page was loaded
        moved = {**VM_DISK, "path": "/var/lib/libvirt/images/moved.qcow2"}
        self.client.force_login(self.superuser)
        for name in ("edit_volume", "detach_vol", "delete_vol"):
            with self.subTest(name), patch("instances.models.wvmInstance") as mock_wvm, \
                    patch("instances.views.wvmStorage") as mock_storage:
                proxy = mock_wvm.return_value
                proxy.get_disk_devices.return_value = [moved]
                res = self._post(name, {"edit_volume": "1", "dev": "vda", "path": VM_DISK["path"],
                                        "vol_path": VM_DISK["path"], "vol_bus": "virtio"})
                self.assertIn("Disk vda has changed since the page was loaded; reload the page",
                              [str(m) for m in get_messages(res.wsgi_request)])
                proxy.edit_disk.assert_not_called()
                proxy.detach_disk.assert_not_called()
                mock_storage.return_value.del_volume.assert_not_called()

    def test_a_disk_without_a_path_is_detached(self):
        # a network disk with only a host (NBD): the form posts an empty path
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm:
            mock_wvm.return_value.get_disk_devices.return_value = [{**VM_DISK, "path": None}]
            self._post("detach_vol", {"dev": "vda", "path": ""})
            mock_wvm.return_value.detach_disk.assert_called_once_with("vda")
            mock_wvm.return_value.detach_disk.reset_mock()
            self._post("detach_vol", {"dev": "vda"})  # a form without the path
            mock_wvm.return_value.detach_disk.assert_not_called()

    def test_edit_volume_bus_change_keeps_the_disk_and_applies_options(self):
        from vrtManager.instance import wvmInstance

        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance", autospec=wvmInstance) as mock_wvm:
            proxy = mock_wvm.return_value
            self._mock_disk_options(proxy)
            proxy.get_status.return_value = 1
            res = self._edit_volume_post(vol_bus="sata")
        self.assertEqual(res.status_code, 302)
        proxy.attach_disk.assert_not_called()
        proxy.detach_disk.assert_not_called()
        proxy.edit_disk.assert_called_once()
        self.assertEqual(proxy.edit_disk.call_args.args[0], "vda")
        self.assertEqual(proxy.edit_disk.call_args.args[4], "sata")

    def test_edit_volume_keeps_current_format_when_field_is_none_or_empty(self):
        self.client.force_login(self.superuser)
        for value in ("None", ""):
            with self.subTest(vol_format=value), patch("instances.models.wvmInstance") as mock_wvm:
                proxy = mock_wvm.return_value
                self._mock_disk_options(proxy)
                self._edit_volume_post(vol_format=value)
                proxy.edit_disk.assert_called_once()
                self.assertEqual(proxy.edit_disk.call_args[0][6], VM_DISK["format"])

    def test_disk_names_with_trailing_newline_are_rejected(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmCreate"
        ) as mock_create, patch("instances.views.wvmStorage"):
            self._mock_disk_options(mock_wvm.return_value)
            self._post(
                "add_new_vol",
                {"storage": "default", "name": "disk\n", "format": "qcow2", "size": "1",
                 "bus": "virtio", "cache": "default"},
            )
        mock_create.return_value.create_volume.assert_not_called()

    def test_add_new_vol_attaches_the_format_the_pool_created(self):
        self.client.force_login(self.superuser)
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.wvmCreate"
        ) as mock_create, patch("instances.views.wvmStorage") as mock_storage:
            proxy = mock_wvm.return_value
            self._mock_disk_options(proxy)
            mock_create.return_value.create_volume.return_value = "/mnt/nfs/disk.img"
            pool = mock_storage.return_value
            pool.get_type.return_value = "netfs"
            pool.get_volume_type.return_value = "file"
            pool.get_volume_format_type.return_value = "raw"  # a netfs pool creates raw
            self._post(
                "add_new_vol",
                {"storage": "nfs", "name": "disk", "format": "qcow2", "size": "1", "bus": "virtio", "cache": "default"},
            )
        pool.get_volume_format_type.assert_called_once_with("disk.img")
        self.assertEqual(proxy.attach_disk.call_args.kwargs["format_type"], "raw")

    def test_edit_volume_accepts_a_disk_without_any_driver_format(self):
        self.client.force_login(self.superuser)
        no_format_disk = dict(VM_DISK, format=None)
        with patch("instances.models.wvmInstance") as mock_wvm:
            proxy = mock_wvm.return_value
            self._mock_disk_options(proxy)
            proxy.get_disk_devices.return_value = [no_format_disk]
            self._edit_volume_post(vol_format="None")
        proxy.edit_disk.assert_called_once()
        self.assertEqual(proxy.edit_disk.call_args[0][6], "")
