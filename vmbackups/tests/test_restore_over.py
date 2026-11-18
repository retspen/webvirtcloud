"""backup.restore_over: a ready backup restored over its own shut-off VM.
The disks are copied as new volumes, the old ones stay; then the switch
(NVRAM, TPM state, the disks' sources), recorded first and finished by
recovery."""

import contextlib
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import libvirt
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.utils import timezone
from lxml import etree

from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from operations import jobs
from operations.jobs import Context
from operations.models import Claim, Operation, acquire
from vmbackups.jobs import RestoreOver, _owner
from vmbackups.models import Backup, BackupFile, BackupTarget, BackupTargetPool
from vrtManager.util import OperationError

GIB = 1024**3
WORKER = "wvc-test:1:a"
NVRAM = "/var/lib/libvirt/qemu/nvram/vm1_VARS.fd"
CURRENT = (
    "<domain type='kvm'><name>vm1</name><uuid>51515151-0000-4000-8000-000000000001</uuid>"
    f"<os><type arch='x86_64' machine='q35'>hvm</type><nvram>{NVRAM}</nvram></os><devices>"
    "<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='/pool/vm1.qcow2'/><target dev='vda'/></disk>"
    "<interface type='network'><mac address='52:54:00:00:00:01'/><source network='default'/></interface>"
    "</devices></domain>"
)


def error(code):
    err = libvirt.libvirtError("x")
    err.err = (code,)
    return err


class RestoreOverTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("ro_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.51", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="51515151-0000-4000-8000-000000000001")
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u")
        self.backup = Backup.objects.create(target=self.target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                            compute_name="h1", state=Backup.READY,
                                            manifest={"nvram": "copied", "tpm": "none"})
        Backup.objects.filter(pk=self.backup.pk).update(created_at=timezone.make_aware(timezone.datetime(2026, 11, 17, 11, 40)))
        self.backup.refresh_from_db()
        prefix = self.backup.prefix
        self.files = {f"{prefix}-nvram.fd": b"vars", f"{prefix}-tpm-tpm2-00.permall": b"state"}
        BackupFile.objects.create(backup=self.backup, role=BackupFile.DISK, dev="vda", volume=f"{prefix}-vda.qcow2",
                                  format="qcow2", capacity=GIB)
        self.add_small(BackupFile.NVRAM, "", f"{prefix}-nvram.fd")

        self.proxy = MagicMock()
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_SHUTOFF
        self.proxy.instance.snapshotNum.return_value = 0
        self.proxy.instance.name.return_value = "vm1"
        self.proxy.instance.autostart.return_value = 0
        self.proxy.instance.hasManagedSaveImage.return_value = 0
        self.proxy.instance.UUIDString.return_value = self.vm.uuid
        self.proxy.get_tpm.return_value = None
        self.proxy.backup_plan.return_value = {
            "disks": [{"dev": "vda", "path": "/pool/vm1.qcow2", "pool": "default", "format": "qcow2", "capacity": GIB}],
            "nvram": NVRAM, "tpm": False}
        self.proxy._XMLDesc.return_value = CURRENT
        self.dest = MagicMock()
        self.dest.name.return_value = "default"
        self.dest.info.return_value = [2, 100 * GIB, 0, 100 * GIB]
        self.dest.storageVolLookupByName.side_effect = error(libvirt.VIR_ERR_NO_STORAGE_VOL)
        self.proxy.file_pools.return_value = {"default": (self.dest, "/pool")}
        self.nvram_pool, self.tpm_pool = MagicMock(), MagicMock()
        self.tpm_pool.listVolumes.return_value = [".lock", "tpm2-00.permall"]
        self.proxy._nvram_pool.side_effect = lambda: contextlib.nullcontext(self.nvram_pool)
        self.proxy._tpm_pool.side_effect = lambda uuid, build=False: contextlib.nullcontext(self.tpm_pool)
        self.events = []
        self.proxy.upload_volume.side_effect = lambda pool, name, data, **kw: self.events.append(("upload", name, data, kw))
        self.proxy._defineXML.side_effect = lambda xml: self.events.append(("define", xml))
        self.tpool = MagicMock()
        self.tpool.storageVolLookupByName.return_value.info.return_value = [0, GIB, GIB]
        self.storage = MagicMock()
        self.storage.clone_volume.side_effect = lambda vol, name, **kw: f"/pool/{name}"
        self.removed = []
        for name, value in (
            ("vmbackups.jobs.wvmBackup", MagicMock(return_value=self.proxy)),
            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.tpool)),
            ("vmbackups.jobs.get_file", MagicMock(side_effect=lambda conn, pool, name: self.files[name])),
            ("vmbackups.jobs.wvmStorage", MagicMock(return_value=self.storage)),
            ("vmbackups.jobs.remove_files", MagicMock(side_effect=self.remove)),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_small(self, role, dev, volume):
        data = self.files[volume]
        BackupFile.objects.create(backup=self.backup, role=role, dev=dev, volume=volume, size=len(data),
                                  sha256=hashlib.sha256(data).hexdigest())

    def remove(self, pool, names):
        names = list(names)
        self.removed.extend(names)
        self.events.append(("remove", names))

    def with_tpm(self):
        self.backup.manifest = {"nvram": "copied", "tpm": "copied"}
        self.backup.save()
        self.add_small(BackupFile.TPM, "tpm2-00.permall", f"{self.backup.prefix}-tpm-tpm2-00.permall")
        self.proxy.get_tpm.return_value = "emulator"
        self.proxy.backup_plan.return_value["tpm"] = True

    def submit(self):
        op = jobs.submit("backup.restore_over", self.admin, {"backup": str(self.backup.uuid)}, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op

    def run_job(self, op):
        return RestoreOver().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def interrupted(self, op):
        with self.assertRaises(Exception):
            self.run_job(op)
        op.refresh_from_db()
        return op

    def refused(self, *texts):
        with self.assertRaises(OperationError) as caught:
            self.run_job(self.submit())
        for text in texts:
            self.assertIn(text, str(caught.exception))
        self.storage.clone_volume.assert_not_called()

    def defined(self):
        return etree.fromstring(next(e[1] for e in self.events if e[0] == "define"))

    def test_the_disks_are_copied_as_new_volumes_then_switched(self):
        op = self.submit()
        self.assertEqual((op.intent["over"]["disks"], op.intent["names"]), ({"vda": "default"}, {"vda": "vm1-vda-20261117-1140.qcow2"}))
        self.assertTrue(Claim.objects.filter(operation=op, resource=f"volume:{self.compute.pk}:default/vm1-vda-20261117-1140.qcow2",
                                             mode=Claim.EXCLUSIVE).exists())
        self.assertTrue(Claim.objects.filter(operation=op, resource=f"instance:{self.vm.uuid}", mode=Claim.EXCLUSIVE).exists())
        self.run_job(op)
        self.storage.clone_volume.assert_called_once()
        self.assertEqual(self.storage.clone_volume.call_args.args[1], "vm1-vda-20261117-1140.qcow2")
        tree = self.defined()
        self.assertEqual(tree.xpath("devices/disk/source/@file"), ["/pool/vm1-vda-20261117-1140.qcow2"])
        self.assertEqual(tree.xpath("devices/interface/mac/@address"), ["52:54:00:00:00:01"])  # the VM's own
        # the NVRAM file replaced in place, before the define
        self.assertEqual(self.events[0], ("remove", ["vm1_VARS.fd"]))
        self.assertEqual(self.events[1], ("upload", "vm1_VARS.fd", b"vars", {"owner": _owner(), "mode": "0600"}))
        self.assertEqual(self.events[-1][0], "define")
        op.refresh_from_db()
        self.assertTrue(op.intent["switching"])
        self.assertNotIn("/pool/vm1.qcow2", self.removed)  # the old volume stays

    def test_the_chain_ends(self):
        self.run_job(self.submit())
        # its disks are replaced: their bitmaps are not the VM's any more
        self.proxy.drop_checkpoint_metadata.assert_called_once_with()

    def test_the_tpm_state_is_replaced(self):
        self.with_tpm()
        self.run_job(self.submit())
        self.assertIn(("remove", ["tpm2-00.permall"]), self.events)  # not swtpm's .lock
        self.assertIn(("upload", "tpm2-00.permall", b"state", {"owner": (0, 0), "mode": "0600"}), self.events)
        self.proxy._tpm_pool.assert_called_with(self.vm.uuid, build=True)

    def test_state_never_written_is_removed(self):
        self.backup.files.filter(role=BackupFile.NVRAM).delete()
        self.backup.manifest = {"nvram": "never written", "tpm": "never written"}
        self.backup.save()
        self.proxy.get_tpm.return_value = "emulator"
        self.proxy.backup_plan.return_value["tpm"] = True
        self.run_job(self.submit())
        self.assertIn(("remove", ["vm1_VARS.fd"]), self.events)
        self.assertIn(("remove", ["tpm2-00.permall"]), self.events)
        self.assertEqual([e for e in self.events if e[0] == "upload"], [])

    def test_a_running_vm_is_refused(self):
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        with self.assertRaisesMessage(OperationError, "Shut the VM down"):
            self.submit()

    def test_a_vm_with_snapshots_is_refused(self):
        self.proxy.instance.snapshotNum.return_value = 2
        with self.assertRaisesMessage(OperationError, "snapshots"):
            self.submit()

    def test_other_disks_are_refused(self):
        self.proxy.backup_plan.return_value["disks"].append(
            {"dev": "vdb", "path": "/pool/vm1-b.raw", "pool": "default", "format": "raw", "capacity": GIB})
        with self.assertRaisesMessage(OperationError, "vdb"):
            self.submit()

    def test_firmware_or_tpm_changed_since_the_backup_is_refused(self):
        self.proxy.backup_plan.return_value["nvram"] = None
        with self.assertRaisesMessage(OperationError, "UEFI"):
            self.submit()
        self.proxy.backup_plan.return_value["nvram"] = NVRAM
        self.proxy.backup_plan.return_value["tpm"] = True
        with self.assertRaisesMessage(OperationError, "TPM"):
            self.submit()

    def test_a_backup_without_its_vm_is_refused(self):
        Backup.objects.filter(pk=self.backup.pk).update(instance=None)
        with self.assertRaisesMessage(OperationError, "new VM"):
            self.submit()

    def test_a_name_taken_after_the_job_was_queued_is_refused_and_nothing_removed(self):
        op = self.submit()
        self.dest.storageVolLookupByName.side_effect = None
        with self.assertRaisesMessage(OperationError, "vm1-vda-20261117-1140.qcow2"):
            self.run_job(op)
        self.storage.clone_volume.assert_not_called()
        self.assertEqual(self.removed, [])

    def test_the_same_backup_restored_over_again_takes_the_next_free_name(self):
        # the VM runs from the first restore's copy; an administrator's restore kept the disk before it too
        self.dest.listVolumes.return_value = ["vm1.qcow2", "vm1-vda-20261117-1140.qcow2", "vm1-vda-20261117-1140-2.qcow2"]
        op = self.submit()
        self.assertEqual(op.intent["names"], {"vda": "vm1-vda-20261117-1140-3.qcow2"})
        self.run_job(op)
        self.assertEqual(self.defined().xpath("devices/disk/source/@file"), ["/pool/vm1-vda-20261117-1140-3.qcow2"])

    def test_disks_changed_after_the_job_was_queued_are_refused(self):
        op = self.submit()
        self.proxy.backup_plan.return_value["disks"][0]["pool"] = "other"
        with self.assertRaisesMessage(OperationError, "changed"):
            self.run_job(op)

    def test_a_vm_started_before_the_switch_stops_it_and_the_copies_go(self):
        self.storage.clone_volume.side_effect = lambda vol, name, **kw: (
            setattr(self.proxy.get_status, "return_value", libvirt.VIR_DOMAIN_RUNNING) or f"/pool/{name}")
        op = self.interrupted(self.submit())
        self.assertNotIn("switching", op.intent)
        outcome = RestoreOver().reconcile(op)
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertIn("vm1-vda-20261117-1140.qcow2", self.removed)
        self.assertEqual([e for e in self.events if e[0] in ("upload", "define")], [])

    def test_recovery_finishes_a_switch(self):
        self.proxy._defineXML.side_effect = RuntimeError("worker gone")
        op = self.interrupted(self.submit())
        self.assertTrue(op.intent["switching"])
        self.proxy._defineXML.side_effect = lambda xml: self.events.append(("define", xml))
        self.events.clear()
        self.assertEqual(RestoreOver().reconcile(op).state, Operation.SUCCEEDED)
        self.assertEqual(self.defined().xpath("devices/disk/source/@file"), ["/pool/vm1-vda-20261117-1140.qcow2"])
        self.assertNotIn("vm1-vda-20261117-1140.qcow2", self.removed)

    def test_recovery_of_a_done_switch_changes_nothing_again(self):
        op = self.submit()
        self.run_job(op)
        op.refresh_from_db()
        # the VM booted outside the panel after the define, before the job's end was recorded
        self.proxy._XMLDesc.return_value = self.events[-1][1]
        self.events.clear()
        self.assertEqual(RestoreOver().reconcile(op).state, Operation.SUCCEEDED)
        self.assertEqual(self.events, [])

    def test_a_saved_state_made_during_the_copy_stops_the_switch(self):
        def copy(vol, name, **kw):
            self.proxy.backup_plan.side_effect = OperationError("vm1 has a saved state")
            return f"/pool/{name}"

        self.storage.clone_volume.side_effect = copy
        op = self.interrupted(self.submit())
        self.assertNotIn("switching", op.intent)
        self.assertEqual([e for e in self.events if e[0] in ("upload", "define")], [])

    def test_recovery_of_a_vm_moved_is_uncertain(self):
        self.proxy._defineXML.side_effect = RuntimeError("worker gone")
        op = self.interrupted(self.submit())
        Instance.objects.filter(pk=self.vm.pk).update(compute=Compute.objects.create(
            name="h2", hostname="192.0.2.52", login="u", password="p", type=1))
        self.assertEqual(RestoreOver().reconcile(op).state, Operation.UNCERTAIN)

    def test_recovery_of_a_switch_on_a_started_vm_is_uncertain(self):
        self.proxy._defineXML.side_effect = RuntimeError("worker gone")
        op = self.interrupted(self.submit())
        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.assertEqual(RestoreOver().reconcile(op).state, Operation.UNCERTAIN)

    def test_a_copy_in_flight_is_uncertain(self):
        self.storage.clone_volume.side_effect = RuntimeError("worker gone")
        op = self.interrupted(self.submit())
        self.assertEqual(RestoreOver().reconcile(op).state, Operation.UNCERTAIN)
        self.assertEqual(self.removed, [])

    def test_the_log_row(self):
        op = self.submit()
        self.run_job(op)
        entry = RestoreOver().log_entry(op, Operation.SUCCEEDED)
        self.assertEqual(entry[:3], ("h1", "vm1", self.vm.uuid))
        self.assertEqual(entry[3], "VM vm1: restored over from its backup taken 2026-11-17 11:40")

    def test_autostart_is_off_during_the_switch(self):
        self.proxy.instance.autostart.return_value = 1
        self.proxy.instance.setAutostart.side_effect = lambda on: self.events.append(("autostart", on))
        self.run_job(self.submit())
        kinds = [e[0] for e in self.events]
        self.assertEqual(self.events[0], ("autostart", 0))  # a host booting mid-switch starts nothing
        self.assertEqual(self.events[-1], ("autostart", 1))
        self.assertLess(kinds.index("define"), len(kinds) - 1)

    def test_recovery_of_a_switch_on_a_saved_vm_is_uncertain(self):
        self.proxy._defineXML.side_effect = RuntimeError("worker gone")
        op = self.interrupted(self.submit())
        self.proxy.instance.hasManagedSaveImage.return_value = 1
        self.assertEqual(RestoreOver().reconcile(op).state, Operation.UNCERTAIN)

    def test_a_copy_libvirt_refused_fails_and_removes_the_copies(self):
        self.storage.clone_volume.side_effect = libvirt.libvirtError("No space left on device")
        op = self.interrupted(self.submit())
        self.assertEqual(RestoreOver().reconcile(op).state, Operation.FAILED)
        self.assertIn("vm1-vda-20261117-1140.qcow2", self.removed)  # libvirt may have made it before failing

    def test_the_page_shows_the_volumes_then_submits(self):
        from django.urls import reverse
        from lxml import html as lxml_html

        self.client.force_login(self.admin)
        url = reverse("vmbackups:restore_over", args=[self.backup.uuid])
        page = lxml_html.fromstring(self.client.get(url).content)
        row = [" ".join(td.text_content().split()) for td in page.xpath("//table[@id='restore-over-disks']/tbody/tr/td")]
        self.assertEqual(row, ["vda", "/pool/vm1.qcow2", "default / vm1-vda-20261117-1140.qcow2"])
        self.assertIn("UEFI", page.text_content())
        response = self.client.post(url, {"submission_key": "key-page-over1"})
        op = Operation.objects.get(kind="backup.restore_over")
        self.assertRedirects(response, reverse("operations:job", args=[op.pk]), fetch_redirect_response=False)

    def test_the_page_says_why_not(self):
        from django.urls import reverse

        self.proxy.get_status.return_value = libvirt.VIR_DOMAIN_RUNNING
        self.client.force_login(self.admin)
        response = self.client.get(reverse("vmbackups:restore_over", args=[self.backup.uuid]))
        self.assertContains(response, "Shut the VM down")
        self.assertNotContains(response, "key-")  # no form

    def test_only_superusers_and_a_backup_with_its_vm(self):
        from django.urls import reverse

        url = reverse("vmbackups:restore_over", args=[self.backup.uuid])
        self.client.force_login(get_user_model().objects.create_user("ro_user", password="pw"))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        Backup.objects.filter(pk=self.backup.pk).update(instance=None)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_api_restore_over(self):
        self.client.force_login(self.admin)
        response = self.client.post(f"/api/v1/backups/{self.backup.uuid}/restore-over/", {"submission_key": "key-api-over1"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["kind"], "backup.restore_over")
