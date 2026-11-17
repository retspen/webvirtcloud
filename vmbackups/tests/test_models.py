from uuid import UUID

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase

from computes.models import Compute
from instances.models import Instance
from operations.claims import backup_key, backup_target_key
from vmbackups.models import Backup, BackupTarget, BackupTargetPool


class BackupModelTests(TestCase):
    def setUp(self):
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.10", login="u", password="p", type=1)
        self.target = BackupTarget.objects.create(name="nfs1")

    def backup(self, instance=None):
        return Backup.objects.create(
            target=self.target, instance=instance, vm_uuid="11111111-1111-1111-1111-111111111111", vm_name="vm1", compute_name="h1"
        )

    def test_a_backup_keeps_its_vm_when_the_vm_row_goes(self):
        vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="11111111-1111-1111-1111-111111111111")
        backup = self.backup(vm)
        vm.delete()
        backup.refresh_from_db()
        self.assertIsNone(backup.instance)
        self.assertEqual((backup.vm_name, backup.vm_uuid), ("vm1", "11111111-1111-1111-1111-111111111111"))

    def test_a_target_with_backups_cannot_be_deleted(self):
        self.backup()
        with self.assertRaises(ProtectedError):
            self.target.delete()

    def test_one_pool_per_target_and_compute(self):
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u1")
        self.assertEqual(self.target.pool_on(self.compute).pool, "b1")
        with self.assertRaises(IntegrityError):
            BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b2", pool_uuid="u2")

    def test_a_removed_compute_takes_its_pool_row(self):
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="u1")
        self.backup()
        self.compute.delete()
        self.assertFalse(self.target.pools.exists())
        self.assertEqual(self.target.backups.count(), 1)

    def test_a_target_without_a_pool_on_a_compute(self):
        self.assertIsNone(self.target.pool_on(self.compute))

    def test_prefix(self):
        backup = Backup(uuid=UUID("00000000-0000-4000-8000-000000000001"))
        self.assertEqual(backup.prefix, "wvc-00000000-0000-4000-8000-000000000001")

    def test_claim_keys(self):
        self.assertEqual(backup_target_key(3), "backup_target:3")
        self.assertEqual(backup_key("00000000-0000-4000-8000-000000000001"), "backup:00000000-0000-4000-8000-000000000001")
