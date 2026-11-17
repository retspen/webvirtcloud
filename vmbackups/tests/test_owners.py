"""VM owners with the backup permission: their VMs, targets open to owners,
their own backups, and the backup quota (layer 6)."""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase

from accounts.models import UserAttributes, UserInstance
from appsettings.settings import get_settings
from computes.models import Compute
from instances.models import Instance
from operations import jobs
from operations.jobs import Context
from operations.models import Operation, acquire
from vmbackups.jobs import CreateBackup
from vmbackups.models import Backup, BackupFile, BackupTarget, BackupTargetPool
from vmbackups.tests.test_create import plan, proxy, target_pool
from vrtManager.util import OperationError

GIB = 1024**3
WORKER = "wvc-test:1:a"
DEFINITION = (
    "<domain type='kvm'><name>vm1</name><uuid>71717171-0000-4000-8000-000000000001</uuid>"
    "<memory unit='KiB'>2097152</memory><vcpu>2</vcpu>"
    "<os><type arch='x86_64' machine='pc-q35-10.1'>hvm</type></os><devices><emulator>/usr/libexec/qemu-kvm</emulator>"
    "<disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='/pool/a.qcow2'/><target dev='vda'/></disk>"
    "</devices></domain>"
).encode()


class OwnerTests(TransactionTestCase):
    def setUp(self):
        get_settings()
        self.owner = get_user_model().objects.create_user("bk_owner", password="pw")
        self.owner.user_permissions.add(Permission.objects.get(codename="backup_instances"))
        self.compute = Compute.objects.create(name="h1", hostname="192.0.2.71", login="u", password="p", type=1)
        self.vm = Instance.objects.create(compute=self.compute, name="vm1", uuid="71717171-0000-4000-8000-000000000001")
        UserInstance.objects.create(user=self.owner, instance=self.vm, is_change=True)
        self.target = BackupTarget.objects.create(name="nfs1", owners=True)
        BackupTargetPool.objects.create(target=self.target, compute=self.compute, pool="b1", pool_uuid="pool-uuid")
        UserAttributes.objects.update_or_create(user=self.owner, defaults={"max_backup_size": 10})
        self.proxy = proxy()
        self.proxy.backup_plan.return_value = plan()
        self.proxy.backup_plan.return_value["disks"][0]["allocation"] = 4 * GIB
        self.pool = target_pool()
        for name, value in (
            ("vmbackups.jobs.wvmBackup", MagicMock(return_value=self.proxy)),
            ("vmbackups.jobs.target_pool", MagicMock(return_value=self.pool)),
            ("vmbackups.jobs.put_file", MagicMock(return_value="sha")),
            ("vmbackups.jobs.remove_files", MagicMock()),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def submit(self, kind, raw, user=None):
        op = jobs.submit(kind, user or self.owner, raw, f"key-{uuid4().hex[:12]}")
        acquire(WORKER, "wvc-test")
        Operation.objects.filter(pk=op.pk).update(state=Operation.RUNNING, worker=WORKER)
        op.refresh_from_db()
        return op

    def back_up(self, **raw):
        return self.submit("backup.create", {"instance": self.vm.pk, "target": self.target.pk, **raw})

    def taken(self, size_gib, user=None, policy=None, state=Backup.READY):
        return Backup.objects.create(target=self.target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                     compute_name="h1", state=state, size=size_gib * GIB, taken_by=user or self.owner,
                                     policy=policy)

    # backing up

    def test_an_owner_backs_up_their_vm_and_the_backup_is_theirs(self):
        op = self.back_up()
        CreateBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))
        backup = Backup.objects.get(uuid=op.intent["backup"])
        self.assertEqual((backup.state, backup.taken_by), (Backup.READY, self.owner))

    def test_without_the_permission_or_change_rights_nothing_is_backed_up(self):
        self.owner.user_permissions.clear()
        with self.assertRaises(PermissionDenied):
            self.back_up()
        self.owner.user_permissions.add(Permission.objects.get(codename="backup_instances"))
        UserInstance.objects.filter(user=self.owner).update(is_change=False)
        self.owner = get_user_model().objects.get(pk=self.owner.pk)  # a fresh permission cache
        with self.assertRaises(PermissionDenied):
            self.back_up()

    def test_a_target_not_open_to_owners_is_refused(self):
        BackupTarget.objects.filter(pk=self.target.pk).update(owners=False)
        with self.assertRaisesMessage(OperationError, "not open to VM owners"):
            self.back_up()

    def test_an_owner_cannot_act_as_a_schedule(self):
        with self.assertRaises(PermissionDenied):
            self.back_up(policy=1)

    def test_rights_lost_after_the_job_was_queued_stop_it(self):
        op = self.back_up()
        BackupTarget.objects.filter(pk=self.target.pk).update(owners=False)
        with self.assertRaisesMessage(OperationError, "not open to VM owners"):
            CreateBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def test_the_quota_counts_the_owners_own_backups(self):
        self.taken(6)
        self.taken(50, policy=None, user=get_user_model().objects.create_superuser("adm", "a@example.com", "pw"))
        self.taken(50, state=Backup.FAILED)
        op = self.back_up()  # 6 + 4 of 10 GiB: the administrator's and the failed one do not count
        CreateBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))
        jobs.finish(op, jobs.Outcome(Operation.SUCCEEDED))
        with self.assertRaisesMessage(OperationError, "backup quota"):
            self.back_up()  # 6 + the new one's real size + 4
        UserAttributes.objects.filter(user=self.owner).update(max_backup_size=-1)
        self.back_up()

    def test_a_backup_being_made_holds_its_estimate(self):
        op = self.back_up()
        # the run check: another backup of the owner was admitted and made its row meanwhile
        self.taken(7, state=Backup.CREATING)
        with self.assertRaisesMessage(OperationError, "backup quota"):
            CreateBackup().run(op, Context(op, SimpleNamespace(identity=WORKER)))

    def test_an_owners_backups_run_one_at_a_time(self):
        # different VMs, different targets: the run check reads the other's row only after it exists
        op = self.back_up()
        self.assertTrue(op.claims.filter(resource=f"backup_quota:{self.owner.pk}", mode="exclusive").exists())

    def test_no_quota_means_none(self):
        UserAttributes.objects.filter(user=self.owner).update(max_backup_size=0)
        with self.assertRaisesMessage(OperationError, "You have no backup quota"):
            self.back_up()

    def test_the_quota_refusal_names_sizes_a_person_reads(self):
        self.taken(9)
        with self.assertRaisesMessage(OperationError, "The backup needs about 4.0 GiB; 9.0 GiB of your 10 GiB"):
            self.back_up()
        self.proxy.backup_plan.return_value["disks"][0]["allocation"] = 300  # a nearly empty disk: not 0.0
        Backup.objects.all().delete()
        self.taken(10)
        with self.assertRaisesMessage(OperationError, "about 0.1 GiB"):
            self.back_up()

    # deleting

    def test_an_owner_deletes_only_their_own_backups_by_hand(self):
        mine, schedules, others = self.taken(1), self.taken(1), self.taken(1, user=get_user_model().objects.create_user("x"))
        from vmbackups.models import BackupPolicy
        import datetime

        policy = BackupPolicy.objects.create(name="n", target=self.target, time=datetime.time(2), keep=2)
        Backup.objects.filter(pk=schedules.pk).update(policy=policy)
        self.submit("backup.delete", {"backup": str(mine.uuid)})
        for backup in (schedules, others):
            with self.assertRaises(PermissionDenied):
                self.submit("backup.delete", {"backup": str(backup.uuid)})

    # restoring

    def ready_backup(self):
        backup = self.taken(1, user=get_user_model().objects.create_superuser("adm2", "b@example.com", "pw"))
        BackupFile.objects.create(backup=backup, role=BackupFile.DISK, dev="vda", volume=f"{backup.prefix}-vda.qcow2",
                                  format="qcow2", capacity=8 * GIB)
        BackupFile.objects.create(backup=backup, role=BackupFile.DOMAIN, volume=f"{backup.prefix}-domain.xml",
                                  size=len(DEFINITION), sha256=hashlib.sha256(DEFINITION).hexdigest())
        return backup

    def restore(self, backup, **raw):
        return self.submit("backup.restore", {"backup": str(backup.uuid), "compute": self.compute.pk, "pool": "default",
                                              "name": "vm1-restored", **raw})

    def test_an_owner_restores_as_a_new_vm_on_the_vms_host_and_pool_within_the_quota(self):
        backup = self.ready_backup()
        conn = MagicMock()
        with (patch("vmbackups.jobs.wvmConnect", return_value=conn),
              patch("vmbackups.jobs.get_file", return_value=DEFINITION),
              patch("vmbackups.jobs._vm_pool", return_value="default")):
            UserAttributes.objects.filter(user=self.owner).update(max_instances=-1, max_cpus=-1, max_memory=-1,
                                                                  max_disk_size=-1)
            op = self.restore(backup)
            self.assertEqual(op.intent["quota"], {"cpus": 2, "memory": 2048, "disk": 8})
            Operation.objects.all().delete()
            from operations.models import Claim

            Claim.objects.all().delete()
            for raw in ({"compute": Compute.objects.create(name="h2", hostname="192.0.2.72", login="u", password="p",
                                                           type=1).pk}, {"pool": "fast"}):
                with self.assertRaises(PermissionDenied):
                    self.restore(backup, **raw)
            from instances.utils import QuotaExceeded

            # the owner's VMs are read from their hosts: here the quota check answers
            with (patch("vmbackups.jobs.check_user_quota", return_value=QuotaExceeded("cpu", 3, 1)) as check,
                  self.assertRaisesMessage(OperationError, "vCPU quota")):
                self.restore(backup)
            check.assert_called_once_with(self.owner, 1, 2, 2048, 8)

    def test_a_restore_counts_in_the_quota_until_its_vm_is_recorded(self):
        from instances.utils import check_user_quota

        backup = self.ready_backup()
        UserAttributes.objects.filter(user=self.owner).update(max_instances=2, max_cpus=-1, max_memory=-1, max_disk_size=-1)
        with (patch("vmbackups.jobs.wvmConnect", return_value=MagicMock()),
              patch("vmbackups.jobs.get_file", return_value=DEFINITION),
              patch("vmbackups.jobs._vm_pool", return_value="default")):
            self.restore(backup)
        # the owner's VM and the restore make two: one more is over
        self.assertTrue(check_user_quota(self.owner, 1, 0, 0, 0))

    def test_an_owners_restore_over_removes_the_old_disks_not_used_elsewhere(self):
        from vmbackups.jobs import RestoreOver

        backup = self.ready_backup()
        over = {"disks": {"vda": ["default", "vm1-vda-x.qcow2"]}, "old": {"vda": "/pool/a.qcow2"}, "nvram": None, "tpm": False}
        old_vol = MagicMock()
        self.proxy.get_volume_by_path.return_value = old_vol
        self.proxy.paths_used_by_other_domains.return_value = set()
        self.proxy._XMLDesc.return_value = DEFINITION.decode()
        self.proxy.get_status.return_value = 5
        self.proxy.instance.autostart.return_value = 0
        with (patch("vmbackups.jobs._over_plan", return_value=over),
              patch("vmbackups.jobs._check_files"),
              patch("vmbackups.jobs.paths_used_on_other_computes", return_value=set()),
              patch("vmbackups.jobs.wvmStorage") as storage,
              patch("vmbackups.jobs.wvmInstance._refuse_taken"),
              patch("vmbackups.jobs.check_target_space")):
            storage.return_value.clone_volume.return_value = "/pool/vm1-vda-x.qcow2"
            self.proxy.file_pools.return_value = {"default": (MagicMock(), "/pool")}
            op = self.submit("backup.restore_over", {"backup": str(backup.uuid)})
            RestoreOver().run(op, Context(op, SimpleNamespace(identity=WORKER)))
        op.refresh_from_db()
        self.assertEqual(op.intent["remove"], ["/pool/a.qcow2"])
        old_vol.delete.assert_called_once_with(0)

    def test_an_old_disk_used_meanwhile_by_another_vm_is_kept(self):
        from vmbackups.jobs import RestoreOver

        op = SimpleNamespace(intent={"remove": ["/pool/a.qcow2", "/pool/b.qcow2"]}, user=self.owner,
                             params={"backup": ""})
        self.proxy.paths_used_by_other_domains.return_value = {"/pool/a.qcow2"}  # attached since the switch began
        volumes = {}
        self.proxy.get_volume_by_path.side_effect = lambda path: volumes.setdefault(path, MagicMock())
        with patch("vmbackups.jobs.paths_used_on_other_computes", return_value=set()):
            RestoreOver._remove_old(op, self.proxy, self.vm)
        self.assertEqual([p for p, v in volumes.items() if v.delete.called], ["/pool/b.qcow2"])

    def test_an_owner_restores_over_only_disks_no_larger_than_the_vms(self):
        from vmbackups.jobs import _over_plan

        backup = self.ready_backup()  # its vda is 8 GiB; the VM's now 1 GiB
        self.proxy.get_status.return_value = 5
        self.proxy.instance.snapshotNum.return_value = 0
        self.proxy.instance.name.return_value = "vm1"
        self.proxy.backup_plan.return_value = {"disks": [{"dev": "vda", "path": "/pool/a.qcow2", "pool": "default",
                                                          "format": "qcow2", "capacity": GIB}], "nvram": None, "tpm": False}
        with self.assertRaisesMessage(OperationError, "larger"):
            _over_plan(backup, self.proxy, owner=True)
        self.assertTrue(_over_plan(backup, self.proxy, owner=False))

    def test_an_owners_restore_holds_their_quota(self):
        backup = self.ready_backup()
        with (patch("vmbackups.jobs.wvmConnect", return_value=MagicMock()),
              patch("vmbackups.jobs.get_file", return_value=DEFINITION),
              patch("vmbackups.jobs._vm_pool", return_value="default"),
              patch("vmbackups.jobs.check_user_quota", return_value="")):
            op = self.restore(backup)
        self.assertTrue(op.claims.filter(resource=f"quota:user:{self.owner.pk}", mode="exclusive").exists())

    def test_a_template_is_not_backed_up_by_an_owner(self):
        self.owner.is_staff = True  # a staff owner may change a template
        self.owner.save()
        Instance.objects.filter(pk=self.vm.pk).update(is_template=True)
        with self.assertRaises(PermissionDenied):
            self.back_up()

    def test_a_closed_target_stops_an_owners_deletion(self):
        mine = self.taken(1)
        BackupTarget.objects.filter(pk=self.target.pk).update(owners=False)
        with self.assertRaisesMessage(OperationError, "not open to VM owners"):
            self.submit("backup.delete", {"backup": str(mine.uuid)})

    def test_another_owners_vm_is_not_restored_over(self):
        backup = self.ready_backup()
        UserInstance.objects.filter(user=self.owner).delete()
        with self.assertRaises((PermissionDenied, Exception)):
            self.submit("backup.restore_over", {"backup": str(backup.uuid)})

    def test_a_restore_of_another_vms_backup_is_refused(self):
        backup = self.ready_backup()
        other = Instance.objects.create(compute=self.compute, name="vm2", uuid="71717171-0000-4000-8000-000000000002")
        Backup.objects.filter(pk=backup.pk).update(instance=other)
        with self.assertRaises(PermissionDenied):
            self.restore(backup)

    def test_superusers_keep_restore_one_disk(self):
        backup = self.ready_backup()
        with self.assertRaises(PermissionDenied):
            self.submit("backup.restore_disk", {"backup": str(backup.uuid), "dev": "vda", "compute": self.compute.pk,
                                                "pool": "default", "name": "x.qcow2"})

    # pages

    def test_the_restore_page_of_an_owner_names_the_vms_host_and_pool(self):
        from django.urls import reverse
        from lxml import html as lxml_html

        backup = self.ready_backup()
        self.client.force_login(self.owner)
        with patch("vmbackups.views._vm_pool", return_value="default"):
            page = lxml_html.fromstring(self.client.get(reverse("vmbackups:restore", args=[backup.uuid])).content)
        self.assertFalse(page.xpath("//select[@name='compute']|//input[@name='pool']"))
        self.assertIn("On h1, in storage pool default", page.text_content())
        with (patch("vmbackups.views._vm_pool", return_value="default"),
              patch("vmbackups.jobs._vm_pool", return_value="default"),
              patch("vmbackups.jobs.wvmConnect", return_value=MagicMock()),
              patch("vmbackups.jobs.get_file", return_value=DEFINITION),
              patch("vmbackups.jobs.check_user_quota", return_value="")):
            response = self.client.post(reverse("vmbackups:restore", args=[backup.uuid]),
                                        {"name": "vm1-back", "submission_key": "key-owner-restore"})
        op = Operation.objects.get(kind="backup.restore")
        self.assertRedirects(response, reverse("operations:job", args=[op.pk]), fetch_redirect_response=False)
        self.assertEqual((op.params["compute"], op.params["pool"]), (self.compute.pk, "default"))

    def test_the_restore_pages_are_refused_without_the_rights(self):
        from django.urls import reverse

        backup = self.ready_backup()
        self.client.force_login(self.owner)
        BackupTarget.objects.filter(pk=self.target.pk).update(owners=False)
        for name in ("restore", "restore_over"):
            self.assertEqual(self.client.get(reverse(f"vmbackups:{name}", args=[backup.uuid])).status_code, 403)
        BackupTarget.objects.filter(pk=self.target.pk).update(owners=True)
        self.assertEqual(self.client.get(reverse("vmbackups:restore_disk", args=[backup.uuid])).status_code, 403)
        self.assertEqual(self.client.get(reverse("vmbackups:index")).status_code, 403)

    def test_a_superuser_opens_a_target_to_owners(self):
        from django.urls import reverse

        admin = get_user_model().objects.create_superuser("adm3", "c@example.com", "pw")
        self.client.force_login(admin)
        BackupTarget.objects.filter(pk=self.target.pk).update(owners=False)
        response = self.client.post(reverse("vmbackups:target", args=[self.target.pk]), {"owners": "1"}, follow=True)
        self.assertTrue(BackupTarget.objects.get(pk=self.target.pk).owners)
        self.assertContains(response, "VM owners with the backup permission may now use nfs1.")
