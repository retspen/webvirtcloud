from types import SimpleNamespace
from unittest.mock import patch

from appsettings.settings import get_settings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TestCase
from libvirt import libvirtError

from instances.jobs import CreateInstance
from operations import jobs
from operations.jobs import Context
from operations.models import Operation, acquire

PARAMS = {
    "name": "rb-vm", "firmware": "BIOS", "vcpu": 1, "vcpu_mode": "host-model", "memory": 128,
    "hdd_size": 1, "storage": "default", "mac": "52:54:00:aa:04:01", "networks": "default",
    "nwfilter": "", "net_model": "virtio", "cache_mode": "none", "video": "vga",
    "listener_addr": "0.0.0.0", "add_cdrom": "None", "add_input": "None", "virtio": True, "qemu_ga": False,
    "arch": "x86_64", "machine": "q35",
}


class CreateRollbackTestCase(TestCase):
    """Volumes are removed only while the VM is not defined yet."""

    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("rb_admin", "r@example.com", "pw")
        self.compute = Compute.objects.create(name="rb", hostname="192.0.2.41", login="", password="", type=4)

    def run_job(self, **conn_setup):
        with patch("instances.jobs.wvmCreate") as wvm:
            conn = wvm.return_value
            conn.get_cache_modes.return_value = {"none": "Disable cache"}
            conn.get_firmwares.return_value = ["BIOS", "UEFI", "UEFI Secure Boot"]
            conn.get_dom_capabilities.return_value = {"cpu_modes": ["host-model"]}
            conn.get_instances.return_value = []
            conn.create_volume.return_value = "/pool/rb-vm.qcow2"
            op = jobs.submit("instance.create", self.admin, {**PARAMS, "compute": self.compute.pk}, "key-rollback1")
            acquire("wvc-test:1:a", "wvc-test")
            Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
            op.refresh_from_db()
            for attr, value in conn_setup.items():
                getattr(conn, attr).side_effect = value
            with self.assertRaises(Exception):
                CreateInstance().run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
        return conn

    def test_failed_definition_removes_the_new_volume(self):
        conn = self.run_job(create_instance=libvirtError("rejected"))
        conn.delete_volume.assert_called_once_with("/pool/rb-vm.qcow2")

    def test_failure_after_the_definition_keeps_the_volume(self):
        with patch("instances.jobs.Instance.objects.get_or_create", side_effect=RuntimeError("db down")):
            conn = self.run_job()
        conn.create_instance.assert_called_once()
        conn.delete_volume.assert_not_called()
