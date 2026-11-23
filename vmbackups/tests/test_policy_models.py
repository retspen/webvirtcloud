import datetime

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from computes.models import Compute
from instances.models import Instance
from vmbackups.models import Backup, BackupPolicy, BackupRun, BackupTarget


class PolicyModelTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("pm_admin", "a@example.com", "pw")
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.61", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="61616161-0000-4000-8000-000000000001")
        self.target = BackupTarget.objects.create(name="nfs1")
        self.policy = BackupPolicy.objects.create(name="nightly", target=self.target, time=datetime.time(2, 0), keep=7,
                                                  owner=self.admin)
        self.policy.instances.add(self.vm)

    def test_one_run_per_policy_vm_and_day(self):
        BackupRun.objects.create(policy=self.policy, instance=self.vm, day=datetime.date(2026, 11, 17))
        with self.assertRaises(IntegrityError):
            BackupRun.objects.create(policy=self.policy, instance=self.vm, day=datetime.date(2026, 11, 17))

    def test_a_deleted_policy_keeps_its_backups(self):
        backup = Backup.objects.create(target=self.target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                       compute_name="h1", policy=self.policy, state=Backup.READY)
        self.policy.delete()
        backup.refresh_from_db()
        self.assertIsNone(backup.policy)

    def test_the_vms_of_a_policy(self):
        Instance.objects.create(compute=self.compute, name="vm2", uuid="61616161-0000-4000-8000-000000000002")
        Instance.objects.create(compute=self.compute, name="tpl", uuid="61616161-0000-4000-8000-000000000003",
                                is_template=True)
        self.assertEqual([vm.name for vm in self.policy.vms()], ["vm1"])
        whole = BackupPolicy.objects.create(name="host", target=self.target, compute=self.compute, time=datetime.time(3),
                                            keep=3, owner=self.admin)
        self.assertEqual([vm.name for vm in whole.vms()], ["vm1", "vm2"])  # the compute's VMs now, no template

    def test_the_vms_of_a_tag_s_policy(self):
        from computes.models import Tag
        prod = Tag.objects.create(name="prod")
        self.vm.tags.add(prod)
        Instance.objects.create(compute=self.compute, name="tpl", uuid="61616161-0000-4000-8000-000000000004",
                                is_template=True).tags.add(prod)
        tagged = BackupPolicy.objects.create(name="prod", target=self.target, tag=prod, time=datetime.time(3), keep=3,
                                             owner=self.admin)
        self.assertEqual([vm.name for vm in tagged.vms()], ["vm1"])
        Instance.objects.create(compute=self.compute, name="vm0", uuid="61616161-0000-4000-8000-000000000005").tags.add(prod)
        self.assertEqual([vm.name for vm in tagged.vms()], ["vm0", "vm1"])  # the VMs with it now

    def test_missing_state(self):
        self.assertIn(Backup.MISSING, dict(Backup.STATES))
