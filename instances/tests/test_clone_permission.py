"""
Cloning another user's VM must require change permission on it (templates
excepted), and the clone data must not be taken blindly from the POST body.
"""
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from appsettings.models import AppSettings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserInstance
from appsettings.settings import app_settings
from computes.models import Compute
from instances.models import Instance
from instances.utils import get_dhcp_mac_address
from operations.models import Operation

SRC_DISK = {
    "dev": "vda",
    "image": "src-vm.qcow2",
    "storage": "default",
    "path": "/var/lib/libvirt/images/src-vm.qcow2",
    "size": 10 << 30,
    "format": "qcow2",
}


class ClonePermissionTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        clone_perm = Permission.objects.get(codename="clone_instances")
        view_perm = Permission.objects.get(codename="view_instances")

        self.superuser = User.objects.create_superuser(
            username="clone_super", email="clone_super@example.com", password="password"
        )
        self.viewer = User.objects.create_user(username="clone_viewer", password="password")
        self.viewer.user_permissions.add(clone_perm, view_perm)
        self.owner_readonly = User.objects.create_user(
            username="clone_owner_ro", password="password"
        )
        self.owner_readonly.user_permissions.add(clone_perm)
        self.owner_change = User.objects.create_user(
            username="clone_owner_rw", password="password"
        )
        self.owner_change.user_permissions.add(clone_perm)

        self.compute = Compute.objects.create(
            name="clone-compute", hostname="127.0.0.1", login="root", password="", type=1
        )
        self.instance = Instance.objects.create(
            compute=self.compute,
            name="src-vm",
            uuid="12121212-3434-5656-7878-909090909090",
        )
        UserInstance.objects.create(
            instance=self.instance, user=self.owner_readonly, is_change=False
        )
        UserInstance.objects.create(
            instance=self.instance, user=self.owner_change, is_change=True
        )

    @contextmanager
    def mocked_libvirt(self):
        # the name these tests post is the first free one
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.utils.check_user_quota", return_value=""
        ), patch("instances.utils.get_clone_free_names", return_value=["clone-vm", "clone-vm2"]):
            proxy = self.proxy = mock_wvm.return_value
            proxy.get_disk_devices.return_value = [SRC_DISK]
            proxy.get_net_devices.return_value = [{"mac": "52:54:00:aa:bb:cc"}]
            proxy.get_status.return_value = 5
            proxy.get_vcpu.return_value = 1
            proxy.get_memory.return_value = 512
            yield proxy

    def _clone(self, user, data):
        self.client.force_login(user)
        return self.client.post(
            reverse("instances:clone", args=[self.instance.id]),
            data,
            HTTP_REFERER=f"/instances/{self.instance.id}/",
        )

    def _valid_post(self, **extra):
        data = {
            "name": "clone-vm",
            "clone-net-mac-0": "52:54:00:12:34:56",
            "disk-vda": "clone-vm.qcow2",
            "clone-title": "",
            "clone-description": "",
            "submission_key": "key-clone-perm1",
        }
        data.update(extra)
        return data

    def test_viewer_cannot_clone_someone_elses_vm(self):
        with self.mocked_libvirt():
            res = self._clone(self.viewer, self._valid_post())
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Operation.objects.exists())

    def test_owner_without_is_change_cannot_clone(self):
        with self.mocked_libvirt():
            res = self._clone(self.owner_readonly, self._valid_post())
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Operation.objects.exists())

    def test_a_clone_stays_on_the_host_of_its_vm(self):
        # the removed "VM Clone Auto Migrate" setting sent it to a random host
        other = Compute.objects.create(name="other-host", hostname="198.51.100.20", login="", password="", type=4)
        with self.mocked_libvirt(), \
             patch("instances.views.utils.migrate_instance") as migrate, \
             patch.object(app_settings, "CLONE_INSTANCE_AUTO_MIGRATE", "True", create=True), \
             patch("instances.views.Compute.objects.order_by") as random_host:
            random_host.return_value.first.return_value = other
            self._clone(self.owner_change, self._valid_post())
        migrate.assert_not_called()
        self.assertEqual(Operation.objects.get().intent["compute"], self.instance.compute_id)

    def test_viewer_can_clone_a_template(self):
        self.instance.is_template = True
        self.instance.save(update_fields=["is_template"])
        with self.mocked_libvirt():
            self._clone(self.viewer, self._valid_post())
        self.assertEqual(Operation.objects.count(), 1)

    def test_posted_disk_owner_and_unknown_keys_are_ignored(self):
        with self.mocked_libvirt():
            self._clone(
                self.owner_change,
                self._valid_post(disk_owner_uid="4242", disk_owner_gid="4242", evil="x"),
            )
        clone_data = Operation.objects.get().intent["clone"]
        self.assertEqual(
            clone_data["disk_owner_uid"],
            int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_UID),
        )
        self.assertEqual(
            clone_data["disk_owner_gid"],
            int(app_settings.INSTANCE_VOLUME_DEFAULT_OWNER_GID),
        )
        self.assertNotIn("evil", clone_data)

    def test_non_superuser_disk_names_are_derived_by_the_server(self):
        with self.mocked_libvirt():
            self._clone(
                self.owner_change,
                self._valid_post(**{"disk-vda": "../../../etc/passwd"}),
            )
        clone_data = Operation.objects.get().intent["clone"]
        self.assertEqual(clone_data["disk-vda"], "clone-vm.qcow2")

    def test_superuser_unsafe_disk_name_is_rejected(self):
        with self.mocked_libvirt():
            self._clone(
                self.superuser,
                self._valid_post(**{"disk-vda": "x</name><evil/>"}),
            )
        self.assertFalse(Operation.objects.exists())

    def test_superuser_invalid_second_mac_is_rejected(self):
        with self.mocked_libvirt():
            self._clone(
                self.superuser,
                self._valid_post(**{"clone-net-mac-1": "not-a-mac"}),
            )
        self.assertFalse(Operation.objects.exists())

    def test_a_vm_without_a_nic_is_cloned(self):
        for user, auto_name in ((self.superuser, "False"), (self.owner_change, "False"), (self.owner_change, "True")):
            with self.subTest(user.username, auto_name=auto_name), self.mocked_libvirt() as proxy, patch(
                "instances.views.utils.get_clone_free_names", return_value=["auto-clone", "clone-vm"]
            ):
                AppSettings.objects.filter(key="CLONE_INSTANCE_AUTO_NAME").update(value=auto_name)
                proxy.get_net_devices.return_value = []
                Operation.objects.all().delete()
                data = self._valid_post(name="" if auto_name == "True" else "clone-vm")
                del data["clone-net-mac-0"]
                self._clone(user, data)
                self.assertNotIn("clone-net-mac-0", Operation.objects.get().intent["clone"])

    def test_superuser_valid_clone_passes_posted_values(self):
        with self.mocked_libvirt():
            self._clone(
                self.superuser,
                self._valid_post(**{"disk-vda": "custom-name.qcow2", "meta-vda": "true"}),
            )
        clone_data = Operation.objects.get().intent["clone"]
        self.assertEqual(clone_data["disk-vda"], "custom-name.qcow2")
        self.assertEqual(clone_data["meta-vda"], "true")
        self.assertEqual(clone_data["clone-net-mac-0"], "52:54:00:12:34:56")

    def test_non_superuser_clone_skips_disks_without_a_volume(self):
        empty_disk = {"dev": "vdb", "image": None, "storage": None, "path": None,
                      "size": None, "format": None}
        with self.mocked_libvirt() as proxy:
            proxy.get_disk_devices.return_value = [SRC_DISK, empty_disk]
            self._clone(self.owner_change, self._valid_post())
        clone_data = Operation.objects.get().intent["clone"]
        self.assertEqual(clone_data["disk-vda"], "clone-vm.qcow2")
        self.assertIsNone(clone_data["disk-vdb"])

    def test_derived_disk_names_differ(self):
        disks = [dict(SRC_DISK, dev="vdb", image="src-vm-data.qcow2"), dict(SRC_DISK, dev="vdc", image="data.qcow2")]
        with self.mocked_libvirt() as proxy:
            proxy.get_disk_devices.return_value = disks
            self._clone(self.owner_change, self._valid_post())
        clone_data = Operation.objects.get().intent["clone"]
        self.assertEqual((clone_data["disk-vdb"], clone_data["disk-vdc"]), ("clone-vm-data.qcow2", "clone-vm-vdc-data.qcow2"))

    def test_derived_disk_names_are_sanitized_instead_of_rejected(self):
        odd_disk = dict(SRC_DISK, image="my disk@2.qcow2")
        with self.mocked_libvirt() as proxy:
            proxy.get_disk_devices.return_value = [odd_disk]
            self._clone(self.owner_change, self._valid_post())
        self.assertEqual(Operation.objects.count(), 1)
        # the clone's name leads, so a second clone's disk does not take the first one's name
        self.assertEqual(
            Operation.objects.get().intent["clone"]["disk-vda"], "clone-vm-vda-my-disk-2.qcow2"
        )


class DhcpdConfTestCase(TestCase):
    """Clone name and MAC come from the same dhcpd.conf, next to the app."""

    def test_guess_clone_name_and_mac_read_the_app_directory(self):
        self.client.force_login(get_user_model().objects.create_superuser("dhcp_admin", "d@example.com", "pw"))
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=Path(tmp)):
            Path(tmp, "dhcpd.conf").write_text(
                "host clone7.example.com {\n  hardware ethernet 52:54:00:00:07:07;\n}\n"
            )
            with patch("instances.views.app_settings") as app_settings:
                app_settings.CLONE_INSTANCE_DEFAULT_PREFIX = "clone"
                response = self.client.get(reverse("instances:guess_clone_name"))
            self.assertEqual(response.json(), {"name": "clone7"})
            self.assertEqual(get_dhcp_mac_address("clone7"), "52:54:00:00:07:07")


class CloneNameTestCase(TestCase):
    """A user who is not a superuser clones to a name the form offers: one of
    the free names, or with automatic names the first; the server checks it."""

    def setUp(self):
        AppSettings.objects.filter(key="CLONE_INSTANCE_DEFAULT_PREFIX").update(value="copy")
        AppSettings.objects.filter(key="CLONE_INSTANCE_AUTO_NAME").update(value="False")
        self.user = get_user_model().objects.create_user("clone_names", password="pw")
        self.user.user_permissions.add(Permission.objects.get(codename="clone_instances"))
        compute = Compute.objects.create(name="names-compute", hostname="192.0.2.40", login="root", password="", type=1)
        other = Compute.objects.create(name="names-other", hostname="192.0.2.41", login="root", password="", type=1)
        self.instance = Instance.objects.create(compute=compute, name="src-vm", uuid="45454545-3434-5656-7878-909090909090")
        UserInstance.objects.create(instance=self.instance, user=self.user, is_change=True)
        # copy1 is taken on another host: names are the panel's on every host
        Instance.objects.create(compute=other, name="copy1", uuid="45454545-0000-5656-7878-909090909090")
        self.client.force_login(self.user)

    def clone(self, name):
        with patch("instances.models.wvmInstance") as mock_wvm, patch(
            "instances.views.utils.check_user_quota", return_value=""
        ):
            proxy = self.proxy = mock_wvm.return_value
            proxy.get_disk_devices.return_value = [SRC_DISK]
            proxy.get_net_devices.return_value = [{"mac": "52:54:00:aa:bb:cc"}]
            proxy.get_status.return_value = 5
            proxy.get_vcpu.return_value = 1
            proxy.get_memory.return_value = 512
            self.client.post(reverse("instances:clone", args=[self.instance.id]),
                             {"name": name, "submission_key": f"key-names-{name}"})
        op = Operation.objects.first()
        return op and op.intent["name"]

    def test_a_free_name_from_the_list(self):
        self.assertEqual(self.clone("copy2"), "copy2")
        # what the clone adds to the user's quota until its VM is recorded: the
        # source's persistent definition, which it copies
        self.assertEqual(Operation.objects.get().intent["quota"], {"cpus": 1, "memory": 512, "disk": 10})
        self.proxy.get_vcpu.assert_called_with(config=True)
        self.proxy.get_memory.assert_called_with(config=True)

    def test_any_other_name_is_refused(self):
        for name in ("copy1", "my-own-name", "", "copy12"):  # taken, not offered, empty, past the ten offered
            with self.subTest(name=name):
                self.assertIsNone(self.clone(name))

    def test_automatic_names_ignore_the_posted_name(self):
        AppSettings.objects.filter(key="CLONE_INSTANCE_AUTO_NAME").update(value="True")
        self.assertEqual(self.clone("my-own-name"), "copy2")
