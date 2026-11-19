"""backup.verify: a backup's files and those of the backups it builds on read
whole from the target; what is wrong goes on the backup and fails the job."""

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import libvirt
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase
from django.urls import reverse

from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from operations import claims, jobs
from operations.jobs import Cancelled, Context
from operations.models import Claim, Operation, acquire
from operations.utils import words
from vmbackups.jobs import VerifyBackup
from vmbackups.models import Backup, BackupFile, BackupTarget, BackupTargetPool
from vrtManager.util import OperationError

WORKER = "wvc-test:1:v"
DOMAIN = b"<domain/>"


def missing(name):
    err = libvirt.libvirtError(f"Storage volume not found: {name}")
    err.err = (libvirt.VIR_ERR_NO_STORAGE_VOL, 0, str(err), 2, None, None, None, 0, 0)
    return err


class FakePool:
    """The target's volumes: {name: (capacity, format, backing file name, bytes)}."""

    def __init__(self):
        self.volumes = {}

    def refresh(self, flags):
        pass

    def storageVolLookupByName(self, name):
        if name not in self.volumes:
            raise missing(name)
        capacity, fmt, backing, data = self.volumes[name]
        vol = MagicMock()
        vol.name.return_value = name
        vol.path.return_value = f"/backups/{name}"
        vol.info.return_value = [0, capacity, len(data)]
        vol.infoFlags.return_value = [0, capacity, len(data)]  # physical: the file's length
        below = f"<backingStore><path>/backups/{backing}</path></backingStore>" if backing else ""
        vol.XMLDesc.return_value = f"<volume><target><format type='{fmt}'/></target>{below}</volume>"
        vol.data = data
        return vol


def read_sha256(conn, vol, on_read):
    on_read(len(vol.data))
    return hashlib.sha256(vol.data).hexdigest()


class VerifyBackupTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.admin = get_user_model().objects.create_superuser("ver_admin", "v@example.com", "pw")
        compute = Compute.objects.create(name="h1", hostname="192.0.2.41", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=compute, name="vm1", uuid="41414141-0000-4000-8000-000000000001")
        self.target = BackupTarget.objects.create(name="nfs1")
        BackupTargetPool.objects.create(target=self.target, compute=compute, pool="b1", pool_uuid="u")
        self.pool = FakePool()
        self.full = self.backup()
        self.incremental = self.backup(parent=self.full)
        conn = MagicMock()
        conn.download_volume.side_effect = lambda vol: vol.data
        for name, value in (("vmbackups.jobs.wvmConnect", MagicMock(return_value=conn)),
                            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.pool)),
                            ("vmbackups.jobs.read_sha256", read_sha256)):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def backup(self, parent=None):
        backup = Backup.objects.create(target=self.target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                       compute_name="h1", state=Backup.READY, parent=parent,
                                       manifest={"parent": str(parent.uuid)} if parent else {})
        disk = f"{backup.prefix}-vda.qcow2"
        self.pool.volumes[disk] = (1 << 20, "qcow2", f"{parent.prefix}-vda.qcow2" if parent else None, b"disk " + disk.encode())
        BackupFile.objects.create(backup=backup, role=BackupFile.DISK, dev="vda", volume=disk, format="qcow2", capacity=1 << 20)
        domain = f"{backup.prefix}-domain.xml"
        self.pool.volumes[domain] = (len(DOMAIN), "raw", None, DOMAIN)
        BackupFile.objects.create(backup=backup, role=BackupFile.DOMAIN, volume=domain, capacity=len(DOMAIN),
                                  sha256=hashlib.sha256(DOMAIN).hexdigest())
        manifest = json.dumps(backup.manifest).encode()
        self.pool.volumes[f"{backup.prefix}-manifest.json"] = (len(manifest), "raw", None, manifest)
        return backup

    def verify(self, backup=None):
        backup = backup or self.incremental
        op = jobs.submit("backup.verify", self.admin, {"backup": str(backup.uuid)}, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        try:
            return VerifyBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))
        finally:  # ended as far as the next verification's claims go
            Claim.objects.filter(operation=op).delete()

    def damage(self):
        with self.assertRaises(OperationError) as raised:
            self.verify()
        self.incremental.refresh_from_db()
        self.assertTrue(self.incremental.verified_at)
        return str(raised.exception), self.incremental.damage

    def test_a_sound_chain_is_verified_and_its_disks_hashes_are_recorded(self):
        self.verify()
        self.incremental.refresh_from_db()
        self.assertTrue(self.incremental.verified_at)
        self.assertEqual(self.incremental.damage, [])
        for backup in (self.full, self.incremental):
            disk = backup.files.get(role=BackupFile.DISK)
            self.assertEqual(disk.sha256, hashlib.sha256(self.pool.volumes[disk.volume][3]).hexdigest())

    def test_a_disk_changed_since_its_first_verification(self):
        self.verify()
        name = f"{self.full.prefix}-vda.qcow2"
        self.pool.volumes[name] = (*self.pool.volumes[name][:3], b"bit rot")
        text, damage = self.damage()
        self.assertIn(f"The backup's file {name} changed since its first verification", text)
        self.assertEqual(len(damage), 1)
        # verified again once it is sound: the damage goes
        self.pool.volumes[name] = (*self.pool.volumes[name][:3], b"disk " + name.encode())
        self.verify()
        self.incremental.refresh_from_db()
        self.assertEqual(self.incremental.damage, [])

    def test_damage_found_in_the_base_goes_on_the_base_too(self):
        name = f"{self.full.prefix}-vda.qcow2"
        del self.pool.volumes[name]
        self.damage()
        self.full.refresh_from_db()
        self.assertTrue(self.full.verified_at)
        self.assertIn(f"The backup's file {name} is missing from the target", words(self.full.damage))
        # restoring the base alone warns too
        self.assertEqual(self.full.damaged_in_chain(), self.full)

    def test_damage_of_an_incremental_leaves_its_sound_base_verified_and_sound(self):
        del self.pool.volumes[f"{self.incremental.prefix}-vda.qcow2"]
        self.damage()
        self.full.refresh_from_db()
        self.assertTrue(self.full.verified_at)
        self.assertEqual(self.full.damage, [])

    def test_a_file_missing_from_the_base(self):
        name = f"{self.full.prefix}-vda.qcow2"
        del self.pool.volumes[name]
        text, _damage = self.damage()
        self.assertIn(f"The backup's file {name} is missing from the target", text)

    def test_an_incremental_disk_on_another_file(self):
        name = f"{self.incremental.prefix}-vda.qcow2"
        self.pool.volumes[name] = (1 << 20, "qcow2", "other.qcow2", b"x")
        text, _damage = self.damage()
        self.assertIn(f"The backup's file {name} does not build on {self.full.prefix}-vda.qcow2", text)

    def test_a_disk_of_another_size_or_format(self):
        name = f"{self.incremental.prefix}-vda.qcow2"
        backing = f"{self.full.prefix}-vda.qcow2"
        self.pool.volumes[name] = (1 << 20, "raw", backing, b"x")
        self.assertIn(f"The backup's file {name} is not a qcow2 file", self.damage()[0])
        self.pool.volumes[name] = (2 << 20, "qcow2", backing, b"x")
        self.assertIn(f"The backup's file {name} differs from the one written", self.damage()[0])

    def test_an_incremental_disk_on_a_file_of_another_directory(self):
        name = f"{self.incremental.prefix}-vda.qcow2"
        self.pool.volumes[name] = (1 << 20, "qcow2", f"../elsewhere/{self.full.prefix}-vda.qcow2", b"x")
        self.assertIn(f"The backup's file {name} does not build on", self.damage()[0])

    def test_a_full_backup_s_disk_on_a_backing_file(self):
        name = f"{self.full.prefix}-vda.qcow2"
        self.pool.volumes[name] = (1 << 20, "qcow2", "unrelated.qcow2", b"x")
        self.assertIn(f"The backup's file {name} builds on another file", self.damage()[0])

    def test_a_pool_refresh_refused_meanwhile_does_not_stop_it_nor_tell_a_file_missing(self):
        busy = libvirt.libvirtError("pool has asynchronous jobs running")
        with patch.object(FakePool, "refresh", side_effect=busy):
            self.verify()
            self.incremental.refresh_from_db()
            self.assertEqual(self.incremental.damage, [])
            # a file the list does not have yet: perhaps written through another compute
            del self.pool.volumes[f"{self.full.prefix}-vda.qcow2"]
            with self.assertRaises(libvirt.libvirtError):
                self.verify()
        self.incremental.refresh_from_db()
        self.assertEqual(self.incremental.damage, [])

    def test_a_verification_of_a_backup_of_the_chain_waits_for_the_one_running(self):
        jobs.submit("backup.verify", self.admin, {"backup": str(self.incremental.uuid)}, "key-verify0020")
        with self.assertRaises(claims.Busy):
            jobs.submit("backup.verify", self.admin, {"backup": str(self.full.uuid)}, "key-verify0021")

    def test_recovery_of_a_verification_that_found_damage_adds_nothing_to_it(self):
        self.sound_disk = self.pool.volumes[f"{self.full.prefix}-vda.qcow2"]
        del self.pool.volumes[f"{self.full.prefix}-vda.qcow2"]
        self.damage()
        op = Operation.objects.get(kind="backup.verify")
        outcome = VerifyBackup().reconcile(op)
        self.assertEqual(outcome.state, Operation.FAILED)
        self.assertIn("is missing from the target", words(outcome.error))
        # its own result: not what another verification wrote on the backup since, nor a cancel asked too late
        Backup.objects.filter(pk=self.incremental.pk).update(damage=[])
        Operation.objects.filter(pk=op.pk).update(cancel_requested=True)
        op.refresh_from_db()
        self.assertEqual(VerifyBackup().reconcile(op).state, Operation.FAILED)
        self.pool.volumes[f"{self.full.prefix}-vda.qcow2"] = self.sound_disk
        self.verify(self.full)
        self.assertEqual(VerifyBackup().reconcile(Operation.objects.exclude(pk=op.pk).latest("created_at")).state,
                         Operation.SUCCEEDED)
        # recorded by the previous version, without its damage: the backup's row tells
        Operation.objects.filter(pk=op.pk).update(intent={"recorded": True})
        Backup.objects.filter(pk=self.incremental.pk).update(damage=[{"text": "x", "values": {}}])
        op.refresh_from_db()
        self.assertEqual(VerifyBackup().reconcile(op).state, Operation.FAILED)
        # another verification of the backup that ended: not this one's result
        other = jobs.submit("backup.verify", self.admin, {"backup": str(self.incremental.uuid)}, "key-verify0010")
        self.assertEqual(VerifyBackup().reconcile(other).state, Operation.FAILED)

    def test_a_small_file_of_another_length_is_not_read(self):
        name = f"{self.full.prefix}-domain.xml"
        self.pool.volumes[name] = (len(DOMAIN), "raw", None, b"x" * 100)
        conn_reads = []
        with patch("vmbackups.jobs.wvmConnect") as connect:
            connect.return_value.download_volume.side_effect = lambda vol: conn_reads.append(vol.name()) or vol.data
            self.assertIn(f"The backup's file {name} differs from the one written", self.damage()[0])
        self.assertNotIn(name, conn_reads)

    def test_a_manifest_missing_or_changed(self):
        name = f"{self.full.prefix}-manifest.json"
        self.pool.volumes[name] = (8, "raw", None, b"{\"x\": 1}")
        self.assertIn(f"The backup's file {name} differs from the one written", self.damage()[0])
        del self.pool.volumes[name]
        self.assertIn(f"The backup's file {name} is missing from the target", self.damage()[0])

    def test_another_verification_s_first_hash_counts(self):
        disk = self.full.files.get(role=BackupFile.DISK)

        def other_first(conn, vol, on_read):
            BackupFile.objects.filter(pk=disk.pk).update(sha256="0" * 64)  # recorded meanwhile, of another read
            return read_sha256(conn, vol, on_read)

        with patch("vmbackups.jobs.read_sha256", other_first):
            text, _damage = self.damage()
        self.assertIn(f"The backup's file {disk.volume} changed since its first verification", text)
        disk.refresh_from_db()
        self.assertEqual(disk.sha256, "0" * 64)

    def test_a_small_file_that_differs(self):
        name = f"{self.full.prefix}-domain.xml"
        self.pool.volumes[name] = (9, "raw", None, b"<changed/>")
        self.assertIn(f"The backup's file {name} differs from the one written", self.damage()[0])

    def test_a_target_that_cannot_be_read_leaves_the_backup_as_it_was(self):
        with patch("vmbackups.jobs.read_sha256", side_effect=libvirt.libvirtError("stream broke")):
            with self.assertRaises(libvirt.libvirtError):
                self.verify()
        self.incremental.refresh_from_db()
        self.assertIsNone(self.incremental.verified_at)

    def test_a_cancel_stops_the_read_also_of_a_small_backup_and_after_a_crash(self):
        def cancel_then_read(conn, vol, on_read):
            Operation.objects.filter(kind="backup.verify").update(cancel_requested=True)
            return read_sha256(conn, vol, on_read)

        for step in (1, 64 << 20):  # within a file, or between files
            with self.subTest(step=step), patch("vmbackups.jobs.VERIFY_STEP", step), \
                    patch("vmbackups.jobs.read_sha256", cancel_then_read), self.assertRaises(Cancelled):
                self.verify()
        self.incremental.refresh_from_db()
        self.assertIsNone(self.incremental.verified_at)
        op = Operation.objects.filter(kind="backup.verify").first()
        self.assertEqual(VerifyBackup().reconcile(op).state, Operation.CANCELLED)

    def test_a_superuser_demoted_while_it_waited(self):
        op = jobs.submit("backup.verify", self.admin, {"backup": str(self.full.uuid)}, "key-verify0009")
        get_user_model().objects.filter(pk=self.admin.pk).update(is_superuser=False)
        op.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            VerifyBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def test_a_damaged_backup_is_no_base_of_the_next_scheduled_one(self):
        from vmbackups.jobs import _chain_parent
        from vmbackups.models import BackupPolicy
        policy = BackupPolicy.objects.create(name="n", target=self.target, time="02:00", keep=5, full_every=7, owner=self.admin)
        Backup.objects.filter(pk__in=[self.full.pk, self.incremental.pk]).update(policy=policy, checkpoint="c")
        Backup.objects.filter(pk=self.incremental.pk).update(created_at=self.full.created_at + timedelta(minutes=1))
        plan = {"disks": [{"dev": "vda"}]}
        proxy = MagicMock()
        proxy.checkpoint_sizes.return_value = {"vda": 1}
        pool = MagicMock()
        pool.listVolumes.return_value = list(self.pool.volumes)
        self.assertEqual(_chain_parent(policy, self.vm, self.target, plan, proxy, pool)[0], self.incremental)
        Backup.objects.filter(pk=self.full.pk).update(damage=[{"text": "x", "values": {}}])
        self.assertEqual(_chain_parent(policy, self.vm, self.target, plan, proxy, pool), (None, None))

    def test_only_a_superuser_verifies_and_only_a_ready_backup(self):
        owner = get_user_model().objects.create_user("ver_owner", password="pw")
        with self.assertRaises(PermissionDenied):
            jobs.submit("backup.verify", owner, {"backup": str(self.full.uuid)}, "key-verify0001")
        Backup.objects.filter(pk=self.full.pk).update(state=Backup.MISSING)
        with self.assertRaisesRegex(OperationError, "Only a ready backup can be verified"):
            jobs.submit("backup.verify", self.admin, {"backup": str(self.full.uuid)}, "key-verify0002")

    def test_the_page_offers_it_and_shows_what_was_found(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("vmbackups:index"))
        self.assertContains(page, reverse("vmbackups:verify", args=[self.full.uuid]))
        response = self.client.post(reverse("vmbackups:verify", args=[self.full.uuid]), {"submission_key": "key-verify0003"})
        op = Operation.objects.get(kind="backup.verify")
        self.assertRedirects(response, reverse("operations:job", args=[op.pk]), fetch_redirect_response=False)
        Backup.objects.filter(pk=self.full.pk).update(
            damage=[{"text": "The backup's file %(name)s is missing from the target", "values": {"name": "f"}}])
        page = self.client.get(reverse("vmbackups:index"))
        self.assertContains(page, "Damaged")
        self.assertContains(page, "The backup&#x27;s file f is missing from the target")

    def test_a_restore_page_tells_of_damage_in_the_chain(self):
        self.client.force_login(self.admin)
        damage = [{"text": "The backup's file %(name)s is missing from the target", "values": {"name": "base-vda.qcow2"}}]
        page = self.client.get(reverse("vmbackups:restore_disk", args=[self.incremental.uuid]))
        self.assertNotContains(page, "found damaged")
        Backup.objects.filter(pk=self.full.pk).update(damage=damage)
        self.assertEqual(Backup.objects.get(pk=self.incremental.pk).damaged_in_chain(), Backup.objects.get(pk=self.full.pk))
        page = self.client.get(reverse("vmbackups:restore_disk", args=[self.incremental.uuid]))
        self.assertContains(page, "which a verification found damaged")
        self.assertContains(page, "base-vda.qcow2 is missing from the target")
        page = self.client.get(reverse("vmbackups:index"))
        self.assertContains(page, "base-vda.qcow2 is missing from the target")  # under the badge, not only a tooltip
        Backup.objects.filter(pk=self.full.pk).update(damage=[], parent=self.incremental)  # a chain that loops
        self.assertIsNone(Backup.objects.get(pk=self.incremental.pk).damaged_in_chain())
