"""backup.restore: a ready backup made a new VM, its values recorded before
anything is made, checked again before it is defined, recovered by UUID."""

import contextlib
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import libvirt
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserInstance
from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from operations import jobs
from operations.jobs import Context
from operations.models import Operation, acquire
from vmbackups.jobs import RestoreBackup, _owner
from vmbackups.models import Backup, BackupFile, BackupTarget, BackupTargetPool
from vrtManager.util import OperationError

GIB = 1024**3
WORKER = "wvc-test:1:a"
DEFINITION = (
    "<domain type='kvm'><name>vm1</name><uuid>41414141-0000-4000-8000-000000000001</uuid>"
    "<os><type arch='x86_64' machine='pc-q35-10.1'>hvm</type><nvram>/var/lib/libvirt/qemu/nvram/vm1_VARS.fd</nvram></os>"
    "<devices><emulator>/usr/libexec/qemu-kvm</emulator>"
    "<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='/pool/a.qcow2'/><target dev='vda'/></disk>"
    "<interface type='network'><mac address='52:54:00:00:00:01'/><source network='default'/></interface>"
    "</devices></domain>"
).encode()


def error(code):
    err = libvirt.libvirtError("x")
    err.err = (code,)
    return err


class RestoreTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("rs_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.41", login="u", password="p", type=1)
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u")
        self.backup = Backup.objects.create(target=self.target, vm_uuid="41414141-0000-4000-8000-000000000001",
                                            vm_name="vm1", compute_name="h1", state=Backup.READY)
        prefix = self.backup.prefix
        self.files = {f"{prefix}-domain.xml": DEFINITION, f"{prefix}-nvram.fd": b"vars"}
        BackupFile.objects.create(backup=self.backup, role=BackupFile.DISK, dev="vda", volume=f"{prefix}-vda.qcow2",
                                  format="qcow2", capacity=GIB)
        for role, name in ((BackupFile.DOMAIN, "domain.xml"), (BackupFile.NVRAM, "nvram.fd")):
            data = self.files[f"{prefix}-{name}"]
            BackupFile.objects.create(backup=self.backup, role=role, volume=f"{prefix}-{name}", size=len(data),
                                      sha256=hashlib.sha256(data).hexdigest())

        self.conn = MagicMock()
        self.conn.get_instances.return_value = ["vm1"]
        self.dest = MagicMock()
        self.dest.info.return_value = [2, 100 * GIB, 0, 100 * GIB]
        self.dest.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        self.conn.file_pools.return_value = {"default": (self.dest, "/dest")}
        self.conn.wvm.lookupByUUIDString.side_effect = error(libvirt.VIR_ERR_NO_DOMAIN)
        self.nvram_pool = MagicMock()
        self.nvram_pool.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        self.conn._nvram_pool.side_effect = lambda: contextlib.nullcontext(self.nvram_pool)
        self.tpool = MagicMock()
        self.tpool.storageVolLookupByName.return_value.info.return_value = [0, GIB, GIB]
        self.storage = MagicMock()
        self.storage.clone_volume.side_effect = lambda vol, name, **kw: f"/dest/{name}"
        self.removed = []
        for name, value in (
            ("vmbackups.jobs.wvmConnect", MagicMock(return_value=self.conn)),
            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.tpool)),
            ("vmbackups.jobs.get_file", MagicMock(side_effect=lambda conn, pool, name: self.files[name])),
            ("vmbackups.jobs.check_restore_host", MagicMock()),
            ("vmbackups.jobs.wvmStorage", MagicMock(return_value=self.storage)),
            ("vmbackups.jobs.remove_files", MagicMock(side_effect=lambda pool, names: self.removed.extend(names))),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def submit(self, **fields):
        raw = {"backup": str(self.backup.uuid), "compute": self.compute.pk, "pool": "default", "name": "vm1-restored",
               **fields}
        op = jobs.submit("backup.restore", self.admin, raw, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op

    def run_job(self, op):
        return RestoreBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def defined(self):
        from lxml import etree

        return etree.fromstring(self.conn.wvm.defineXML.call_args.args[0])

    def test_the_restored_vm_is_the_restorers(self):
        op = self.submit()
        result = self.run_job(op)
        vm = Instance.objects.get(uuid=op.intent["uuid"])
        self.assertEqual((vm.name, vm.compute), ("vm1-restored", self.compute))
        self.assertTrue(UserInstance.objects.filter(instance=vm, user=self.admin).exists())
        self.assertEqual(result, {"open": reverse("instances:instance", args=[vm.pk])})
        tree = self.defined()
        self.assertEqual(tree.findtext("uuid"), op.intent["uuid"])
        self.assertEqual(tree.xpath("devices/disk/source/@file"), ["/dest/vm1-restored-vda.qcow2"])
        self.assertEqual(tree.xpath("devices/interface/mac/@address"), op.intent["macs"])
        self.assertEqual(tree.xpath("devices/interface/link/@state"), ["down"])
        self.assertEqual(tree.findtext("os/nvram"), "/var/lib/libvirt/qemu/nvram/vm1-restored_VARS.fd")
        self.storage.clone_volume.assert_called_once()
        self.conn.upload_volume.assert_called_once_with(self.nvram_pool, "vm1-restored_VARS.fd", b"vars", owner=_owner(),
                                                        mode="0600")
        self.conn.wvm.lookupByUUIDString.assert_not_called()  # not started

    def test_start_after_restore(self):
        self.conn.wvm.lookupByUUIDString.side_effect = None
        op = self.submit(start=True, connect=True)
        self.run_job(op)
        self.conn.wvm.lookupByUUIDString.return_value.create.assert_called_once_with()
        self.assertEqual(self.defined().xpath("devices/interface/link"), [])

    def test_a_name_used_on_the_host_is_refused_before_copying(self):
        op = self.submit()
        self.conn.get_instances.return_value = ["vm1", "vm1-restored"]  # made with virsh, unknown to the panel
        with self.assertRaisesMessage(OperationError, "A VM named vm1-restored exists on h1"):
            self.run_job(op)
        self.storage.clone_volume.assert_not_called()

    def test_a_name_the_panel_knows_is_refused(self):
        Instance.objects.create(compute=self.compute, name="vm1-restored", uuid="41414141-0000-4000-8000-000000000009")
        with self.assertRaisesMessage(OperationError, "already exists"):
            self.submit()

    def test_a_missing_network_is_refused(self):
        op = self.submit()
        with patch("vmbackups.jobs.check_restore_host",
                   side_effect=OperationError("This host has no network %(name)s", name="default")):
            with self.assertRaisesMessage(OperationError, "no network default"):
                self.run_job(op)
        self.storage.clone_volume.assert_not_called()

    def test_missing_files_are_refused(self):
        op = self.submit()
        self.tpool.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        with self.assertRaisesMessage(OperationError, "is missing from the target"):
            self.run_job(op)
        self.storage.clone_volume.assert_not_called()

    def test_a_changed_small_file_is_refused(self):
        op = self.submit()
        self.files[f"{self.backup.prefix}-domain.xml"] = b"<domain/>"
        with self.assertRaisesMessage(OperationError, "differs from the one written"):
            self.run_job(op)

    def test_a_taken_volume_name_is_refused(self):
        op = self.submit()
        self.dest.storageVolLookupByName.side_effect = None
        with self.assertRaisesMessage(OperationError, "vm1-restored-vda.qcow2 already exists"):
            self.run_job(op)

    def test_an_existing_nvram_file_is_refused_and_never_removed(self):
        # a file of that name may be a removed VM's kept one, or another VM's
        self.nvram_pool.storageVolLookupByName.side_effect = None
        op = self.submit()
        with self.assertRaisesMessage(OperationError, "vm1-restored_VARS.fd"):
            self.run_job(op)
        op.refresh_from_db()
        self.assertNotIn("nvram", op.intent)
        self.storage.clone_volume.assert_not_called()

    def test_recovery_waits_for_an_inactive_destination_pool(self):
        self.conn.upload_volume.side_effect = RuntimeError("worker gone")  # after the disk was copied
        op = self.submit()
        with self.assertRaises(RuntimeError):
            self.run_job(op)
        op.refresh_from_db()
        self.conn.file_pools.return_value = {}  # the destination pool stopped
        with self.assertRaisesMessage(OperationError, "default"):
            RestoreBackup().reconcile(op)
        self.assertEqual(self.removed, [])

    def test_the_copies_names_are_claimed(self):
        from operations.models import Claim

        op = self.submit()
        self.assertEqual(op.intent["volumes"], {"vda": "vm1-restored-vda.qcow2"})
        self.assertTrue(Claim.objects.filter(operation=op, resource=f"volume:{self.compute.pk}:default/vm1-restored-vda.qcow2",
                                             mode=Claim.EXCLUSIVE).exists())
        # the pool written into, shared: not stopped under the restore
        self.assertTrue(Claim.objects.filter(operation=op, resource=f"pool:{self.compute.pk}:default", mode=Claim.SHARED).exists())

    def test_a_copy_in_flight_is_not_removed(self):
        # its name may have been taken meanwhile by another volume: the job is left to the administrator
        self.storage.clone_volume.side_effect = RuntimeError("worker gone")
        op = self.submit()
        with self.assertRaises(RuntimeError):
            self.run_job(op)
        op.refresh_from_db()
        outcome = RestoreBackup().reconcile(op)
        self.assertEqual(outcome.state, Operation.UNCERTAIN)
        self.assertIn("vm1-restored-vda.qcow2", outcome.error[0]["values"]["volumes"])
        self.assertEqual(self.removed, [])

    def with_tpm(self, name="tpm2-00.permall"):
        volume = f"{self.backup.prefix}-tpm-{name}"
        self.files[volume] = b"state"
        BackupFile.objects.create(backup=self.backup, role=BackupFile.TPM, dev=name, volume=volume, size=5,
                                  sha256=hashlib.sha256(b"state").hexdigest())
        self.tpm_pool = MagicMock()
        self.tpm_pool.listVolumes.return_value = [name]
        self.conn._tpm_pool.side_effect = lambda uuid, build=False: contextlib.nullcontext(self.tpm_pool)

    def test_the_tpm_state_goes_to_the_new_vms_directory_before_it_is_defined(self):
        self.with_tpm()
        self.conn.upload_volume.side_effect = lambda *a, **kw: self.conn.wvm.defineXML.assert_not_called()
        op = self.submit()
        self.run_job(op)
        self.assertTrue(op.intent["tpm"])
        self.conn._tpm_pool.assert_called_once_with(op.intent["uuid"], build=True)
        # root's: libvirt makes the state directory swtpm's when the VM starts
        self.conn.upload_volume.assert_called_with(self.tpm_pool, "tpm2-00.permall", b"state", owner=(0, 0), mode="0600")
        self.conn.wvm.defineXML.assert_called_once()

    def refused_tpm_name(self, name):
        self.with_tpm(name)
        with self.assertRaisesMessage(OperationError, name):
            self.run_job(self.submit())
        self.storage.clone_volume.assert_not_called()
        self.conn._tpm_pool.assert_not_called()

    def test_a_tpm_file_name_that_is_a_path_is_refused_before_anything_is_made(self):
        self.refused_tpm_name("../../qemu/nvram/x")

    def test_a_hidden_tpm_file_name_is_refused(self):
        self.refused_tpm_name(".lock")

    def test_recovery_removes_the_tpm_files_of_a_vm_not_defined(self):
        self.with_tpm()
        self.conn.wvm.defineXML.side_effect = RuntimeError("worker gone")
        op = self.submit()
        with self.assertRaises(RuntimeError):
            self.run_job(op)
        op.refresh_from_db()
        self.conn._tpm_pool.reset_mock()
        self.assertEqual(RestoreBackup().reconcile(op).state, Operation.FAILED)
        self.conn._tpm_pool.assert_called_once_with(op.intent["uuid"])
        self.assertIn("tpm2-00.permall", self.removed)

    def test_recovery_before_the_tpm_directory_was_made(self):
        self.with_tpm()
        self.conn._tpm_pool.side_effect = lambda uuid, build=False: contextlib.nullcontext(None)
        self.conn.upload_volume.side_effect = RuntimeError("worker gone")  # the NVRAM file's
        op = self.submit()
        with self.assertRaises(RuntimeError):
            self.run_job(op)
        op.refresh_from_db()
        self.assertEqual(RestoreBackup().reconcile(op).state, Operation.FAILED)

    def test_an_incremental_backup_needs_its_whole_chain(self):
        base = Backup.objects.create(target=self.target, vm_uuid=self.backup.vm_uuid, vm_name="vm1", compute_name="h1",
                                     state=Backup.READY)
        BackupFile.objects.create(backup=base, role=BackupFile.DISK, dev="vda", volume=f"{base.prefix}-vda.qcow2",
                                  format="qcow2", capacity=GIB)
        Backup.objects.filter(pk=self.backup.pk).update(parent=base)
        seen = []
        self.tpool.storageVolLookupByName.side_effect = lambda name: (
            seen.append(name), (_ for _ in ()).throw(error(libvirt.VIR_ERR_NO_STORAGE_VOL))
            if name == f"{base.prefix}-vda.qcow2" else MagicMock(info=MagicMock(return_value=[0, GIB, GIB])))[1]
        with self.assertRaisesMessage(OperationError, f"{base.prefix}-vda.qcow2"):
            self.run_job(self.submit())
        self.storage.clone_volume.assert_not_called()

    def test_a_chain_whose_base_is_gone_is_refused(self):
        Backup.objects.filter(pk=self.backup.pk).update(manifest={"parent": str(uuid4())})
        with self.assertRaisesMessage(OperationError, "builds on a backup that is gone"):
            self.run_job(self.submit())

    def test_the_restore_form_starts_on_the_vms_host(self):
        from vmbackups.forms import RestoreForm

        vm = Instance.objects.create(compute=self.compute, name="vm1", uuid=self.backup.vm_uuid)
        Backup.objects.filter(pk=self.backup.pk).update(instance=vm)
        self.backup.refresh_from_db()
        self.assertEqual(RestoreForm(backup=self.backup).fields["compute"].initial, self.compute)

    def test_a_copy_libvirt_refused_fails_and_removes_the_copies(self):
        self.storage.clone_volume.side_effect = libvirt.libvirtError("No space left on device")
        op = self.submit()
        with self.assertRaises(libvirt.libvirtError):
            self.run_job(op)
        op.refresh_from_db()
        self.assertEqual(RestoreBackup().reconcile(op).state, Operation.FAILED)  # not uncertain: libvirt answered
        self.assertIn("vm1-restored-vda.qcow2", self.removed)

    def test_recovery_starts_a_restored_vm_it_was_asked_to_start(self):
        op = self.submit(start="on")
        self.conn.wvm.lookupByUUIDString.side_effect = None  # defined before the worker stopped, not started
        dom = self.conn.wvm.lookupByUUIDString.return_value
        dom.isActive.return_value = 0
        self.assertEqual(RestoreBackup().reconcile(op).state, Operation.SUCCEEDED)
        dom.create.assert_called_once_with()

    def test_the_nvram_file_is_qemus(self):
        self.run_job(self.submit())
        self.assertEqual(self.conn.upload_volume.call_args.kwargs, {"owner": _owner(), "mode": "0600"})

    def test_maintenance_is_checked_again_before_define(self):
        def copy(vol, name, **kw):
            Compute.objects.filter(pk=self.compute.pk).update(maintenance_since=timezone.now())
            return f"/dest/{name}"

        self.storage.clone_volume.side_effect = copy
        op = self.submit()
        with self.assertRaisesMessage(OperationError, "maintenance"):
            self.run_job(op)
        self.conn.wvm.defineXML.assert_not_called()
        op.refresh_from_db()
        outcome = RestoreBackup().reconcile(op)
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertEqual(self.removed, ["vm1-restored-vda.qcow2", "vm1-restored_VARS.fd"])

    def test_a_host_in_maintenance_is_refused(self):
        Compute.objects.filter(pk=self.compute.pk).update(maintenance_since=timezone.now())
        with self.assertRaisesMessage(OperationError, "maintenance"):
            self.submit()

    def test_recovery_records_a_defined_vm_instead_of_defining_again(self):
        op = self.submit()
        with patch("vmbackups.jobs.record_vm", side_effect=RuntimeError("worker gone")):
            with self.assertRaises(RuntimeError):
                self.run_job(op)
        op.refresh_from_db()
        self.conn.wvm.lookupByUUIDString.side_effect = None
        self.assertEqual(RestoreBackup().reconcile(op).state, Operation.SUCCEEDED)
        self.assertTrue(Instance.objects.filter(uuid=op.intent["uuid"]).exists())
        self.conn.wvm.defineXML.assert_called_once()
        self.assertEqual(self.removed, [])

    def test_only_a_ready_backup_is_restored(self):
        Backup.objects.filter(pk=self.backup.pk).update(state=Backup.FAILED)
        with self.assertRaisesMessage(OperationError, "ready"):
            self.submit()

    def test_the_log_row(self):
        op = self.submit()
        self.run_job(op)
        entry = RestoreBackup().log_entry(op, Operation.SUCCEEDED)
        self.assertEqual(entry[:3], ("h1", "vm1-restored", op.intent["uuid"]))
        self.assertRegex(entry[3], r"^VM vm1-restored: restored from the backup of vm1 taken \d{4}-")

    def test_api_restore(self):
        self.client.force_login(self.admin)
        response = self.client.post(f"/api/v1/backups/{self.backup.uuid}/restore/",
                                    {"compute": self.compute.pk, "name": "vm1-restored", "submission_key": "key-api-rst1"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["kind"], "backup.restore")

    def test_the_restore_page(self):
        self.client.force_login(self.admin)
        url = reverse("vmbackups:restore", args=[self.backup.uuid])
        page = self.client.get(url)
        self.assertContains(page, 'value="vm1-restored"')
        self.assertContains(page, ">h1</option>")
        response = self.client.post(url, {"name": "vm1-restored", "compute": self.compute.pk, "pool": "default",
                                          "submission_key": "key-page-rst1"})
        op = Operation.objects.get()
        self.assertRedirects(response, reverse("operations:job", args=[op.pk]), fetch_redirect_response=False)
