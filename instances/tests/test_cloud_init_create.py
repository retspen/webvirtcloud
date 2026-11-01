"""A new VM can get a cloud-init NoCloud seed: its hostname and the creating
user's SSH keys on a CD-ROM, read at first boot without the network."""

from types import SimpleNamespace
from unittest.mock import patch

import libvirt
from accounts.models import UserSSHKey
from appsettings.settings import get_settings
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from instances.jobs import CreateInstance
from operations.jobs import Context
from operations.models import Operation, acquire
from vrtManager.util import OperationError

from instances.tests.test_create_job import BODY

SEED = "/srv/default/cidata-x.iso"


class CloudInitCreateTestCase(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("ci_admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        UserSSHKey.objects.create(user=self.admin, keyname="laptop", keypublic="ssh-ed25519 AAAA laptop")
        self.compute = Compute.objects.create(name="ci-c", hostname="192.0.2.41", login="root", password="", type=1)
        patcher = patch("instances.jobs.wvmCreate")
        self.conn = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.conn.get_instances.return_value = []
        self.conn.get_cache_modes.return_value = {"none": "Disable cache"}
        self.conn.get_firmwares.return_value = ["BIOS", "UEFI", "UEFI Secure Boot"]
        self.conn.get_dom_capabilities.return_value = {"cpu_modes": ["host-model"]}
        self.conn.get_disk_bus_types.return_value = ["virtio", "sata"]
        self.conn.create_volume.return_value = "/srv/default/api-vm.qcow2"
        self.conn.create_seed.return_value = SEED
        self.conn.get_storage.return_value.XMLDesc.return_value = "<pool type='dir'/>"
        self.conn.get_storage.return_value.name.return_value = "default"

    def post(self, **fields):
        url = f"/api/v1/computes/{self.compute.pk}/instances/create/x86_64/q35/"
        return self.client.post(url, {**BODY, **fields}, content_type="application/json")

    def run_job(self):
        op = Operation.objects.get()
        acquire("wvc-test:1:a", "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker="wvc-test:1:a")
        op.refresh_from_db()
        CreateInstance().run(op, Context(op, SimpleNamespace(identity="wvc-test:1:a")))
        return op

    def test_the_seed_goes_into_the_disks_pool_and_a_cdrom(self):
        self.assertEqual(self.post(cloud_init=True).status_code, 202)
        op = self.run_job()
        pool, uuid, hostname, user_data = self.conn.create_seed.call_args.args
        self.assertEqual((pool, uuid, hostname), ("default", op.intent["uuid"], "api-vm"))
        # the same user-data the HTTP datasource serves
        self.assertEqual(user_data.split(), ["#cloud-config", "ssh_authorized_keys:", "-", "ssh-ed25519", "AAAA", "laptop"])
        cdrom = self.conn.create_instance.call_args.kwargs["volumes"][-1]
        self.assertEqual((cdrom["path"], cdrom["device"], cdrom["bus"]), (SEED, "cdrom", "sata"))

    def test_without_cloud_init_there_is_no_seed(self):
        self.post()
        self.run_job()
        self.conn.create_seed.assert_not_called()

    def test_a_seed_needs_a_cdrom_and_a_directory_pool(self):
        kind = CreateInstance()
        params = kind.normalize({**BODY, "compute": self.compute.pk, "arch": "x86_64", "machine": "q35",
                                 "cloud_init": True, "add_cdrom": "None"})
        with self.assertRaisesRegex(OperationError, "CD-ROM"):
            kind.validate(self.admin, params)
        self.conn.get_storage.return_value.XMLDesc.return_value = "<pool type='rbd'/>"
        self.assertEqual(self.post(cloud_init=True, submission_key="key-rbd00001").status_code, 400)
        self.assertFalse(Operation.objects.exists())

    def test_a_failed_create_deletes_the_seed_too(self):
        self.post(cloud_init=True)
        self.conn.create_instance.side_effect = libvirt.libvirtError("define failed")
        with self.assertRaises(libvirt.libvirtError):
            self.run_job()
        deleted = [c.args[0] for c in self.conn.delete_volume.call_args_list]
        self.assertEqual(deleted, ["/srv/default/api-vm.qcow2", SEED])

    @patch("instances.jobs.wvmConnect")
    def test_recovery_names_a_seed_left_behind(self, conn):
        op = Operation(params={**BODY, "template": "", "cloud_init": True},
                       intent={"compute": self.compute.pk, "uuid": "abababab-0000-1111-2222-333333333333",
                               "name": "api-vm"})
        missing = libvirt.libvirtError("no domain")
        missing.get_error_code = lambda: libvirt.VIR_ERR_NO_DOMAIN
        conn.return_value.wvm.lookupByUUIDString.side_effect = missing
        conn.return_value.wvm.listAllStoragePools.return_value = [
            SimpleNamespace(listVolumes=lambda: ["cidata-abababab-0000-1111-2222-333333333333.iso"])]
        outcome = CreateInstance().reconcile(op)
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertIn("cidata-abababab-0000-1111-2222-333333333333.iso", outcome.error)
