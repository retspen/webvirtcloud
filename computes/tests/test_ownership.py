"""Ownership survives a VM's temporary disappearance or an out-of-band move."""

from datetime import time, timedelta
from unittest.mock import MagicMock

from accounts.models import UserInstance
from computes.models import Compute, Tag
from computes.utils import refresh_instance_database
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from instances.models import Instance, InstanceTombstone
from logs.models import Logs
from operations import claims
from operations.models import Claim
from rest_framework.test import APIClient
from vmbackups.models import Backup, BackupPolicy, BackupTarget
from computes.tests.fakes import Domain

UUID = "44444444-4444-4444-4444-444444444444"


class OwnershipTestCase(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner", password="pw")
        self.host_a = self.compute("host-a")
        self.host_b = self.compute("host-b")

    def compute(self, name):
        compute = Compute.objects.create(name=name, hostname=f"{name}.example", login="", password="", type=1)
        compute.__dict__["proxy"] = MagicMock()
        compute.__dict__["status"] = True  # reachable
        self.on(compute, [])
        return compute

    def on(self, compute, domains):
        compute.proxy.wvm.listAllDomains.return_value = [Domain(n, u) for n, u in domains]

    def owned_vm(self, compute):
        vm = Instance.objects.create(compute=compute, name="vm", uuid=UUID, is_template=True, protected=True)
        UserInstance.objects.create(instance=vm, user=self.owner, is_change=True, is_vnc=True)
        return vm

    def ownership(self, compute):
        vm = Instance.objects.get(compute=compute, uuid=UUID)
        return vm.is_template, [(ui.user, ui.is_change, ui.is_delete, ui.is_vnc) for ui in vm.userinstance_set.all()]

    def rows(self):
        return list(Logs.objects.order_by("id").values_list("user", "host", "message"))

    def test_vm_that_disappears_and_returns_keeps_its_owners(self):
        self.owned_vm(self.host_a)
        refresh_instance_database(self.host_a)  # undefined for a while
        self.assertFalse(Instance.objects.filter(uuid=UUID).exists())

        self.on(self.host_a, [("vm", UUID)])  # defined again
        refresh_instance_database(self.host_a)

        self.assertEqual(self.ownership(self.host_a), (True, [(self.owner, True, False, True)]))
        self.assertFalse(InstanceTombstone.objects.exists())
        self.assertEqual(self.rows(), [
            ("-", "host-a", f"VM vm ({UUID}): kept on the Removed VMs page"),
            ("-", "host-a", f"VM vm ({UUID}): restored from the Removed VMs page"),
        ])

    def test_vm_that_returns_gets_its_protection_schedules_and_backups_back(self):
        vm = Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID, protected=True)
        target = BackupTarget.objects.create(name="t")
        policy = BackupPolicy.objects.create(name="nightly", target=target, time=time(2), keep=1)
        policy.instances.add(vm)
        backup = Backup.objects.create(target=target, instance=vm, vm_uuid=UUID, vm_name="vm", compute_name="host-a",
                                       state=Backup.READY, policy=policy)
        refresh_instance_database(self.host_a)  # undefined for a while
        self.assertEqual(InstanceTombstone.objects.get().policies, [policy.pk])

        self.on(self.host_a, [("vm", UUID)])  # defined again
        refresh_instance_database(self.host_a)

        vm = Instance.objects.get(uuid=UUID)
        self.assertTrue(vm.protected)
        self.assertEqual(list(vm.backup_policies.all()), [policy])
        backup.refresh_from_db()
        self.assertEqual(backup.instance, vm)

    def test_a_schedule_that_chooses_by_tag_since_is_not_given_the_vm(self):
        vm = Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID)
        policy = BackupPolicy.objects.create(name="nightly", target=BackupTarget.objects.create(name="t"),
                                             time=time(2), keep=1)
        policy.instances.add(vm)
        refresh_instance_database(self.host_a)
        BackupPolicy.objects.filter(pk=policy.pk).update(tag=Tag.objects.create(name="prod"))
        self.on(self.host_a, [("vm", UUID)])
        refresh_instance_database(self.host_a)
        self.assertFalse(policy.instances.exists())

    def test_vm_that_returns_does_not_get_a_copys_backups(self):
        target = BackupTarget.objects.create(name="t")
        copy = Instance.objects.create(compute=self.host_b, name="vm", uuid=UUID)
        theirs = Backup.objects.create(target=target, instance=copy, vm_uuid=UUID, vm_name="vm", compute_name="host-b",
                                       state=Backup.READY)
        copy.delete()  # deleted in the panel: its backups stay, unlinked
        Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID, protected=True)
        refresh_instance_database(self.host_a)
        self.on(self.host_a, [("vm", UUID)])
        refresh_instance_database(self.host_a)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.instance)

    def test_an_ownerless_vm_leaves_a_row(self):
        Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID)
        refresh_instance_database(self.host_a)
        self.assertEqual(self.rows(), [("-", "host-a", f"VM vm ({UUID}): left the panel (nothing to keep)")])

    def test_move_seen_on_the_new_host_first(self):
        self.owned_vm(self.host_a)
        self.on(self.host_a, [("vm", UUID)])
        self.on(self.host_b, [("vm", UUID)])
        refresh_instance_database(self.host_b)  # still listed on A: a copy for now
        self.on(self.host_a, [])
        refresh_instance_database(self.host_a)  # gone from A: it moved to B

        self.assertEqual(self.ownership(self.host_b), (True, [(self.owner, True, False, True)]))
        self.assertTrue(Instance.objects.get(compute=self.host_b).protected)
        self.assertFalse(Instance.objects.filter(compute=self.host_a).exists())
        self.assertEqual(self.rows(), [("-", "host-a", f"VM vm ({UUID}): owners moved to host-b")])

    def test_move_seen_on_the_old_host_first(self):
        self.owned_vm(self.host_a)
        refresh_instance_database(self.host_a)
        self.on(self.host_b, [("vm", UUID)])
        refresh_instance_database(self.host_b)

        self.assertEqual(self.ownership(self.host_b), (True, [(self.owner, True, False, True)]))

    def test_copied_uuid_grants_nothing(self):
        self.owned_vm(self.host_a)
        self.on(self.host_a, [("vm", UUID)])
        self.on(self.host_b, [("vm-copy", UUID)])
        refresh_instance_database(self.host_a)
        refresh_instance_database(self.host_b)

        self.assertEqual(self.ownership(self.host_a), (True, [(self.owner, True, False, True)]))
        self.assertEqual(self.ownership(self.host_b), (False, []))

    def test_a_move_to_one_of_two_copies_gives_the_owners_to_neither(self):
        host_c = self.compute("host-c")
        self.owned_vm(self.host_a)
        self.on(self.host_a, [("vm", UUID)])
        for host in (self.host_b, host_c):
            self.on(host, [("vm", UUID)])
            refresh_instance_database(host)
        self.on(self.host_a, [])
        refresh_instance_database(self.host_a)

        self.assertEqual(self.ownership(self.host_b), (False, []))
        self.assertEqual(self.ownership(host_c), (False, []))
        self.assertEqual(InstanceTombstone.objects.get().owners,
                         [{"user": self.owner.id, "is_change": True, "is_delete": False, "is_vnc": True}])

    @override_settings(INSTANCE_OWNERSHIP_RETENTION_DAYS=30)
    def test_ownership_is_kept_for_a_bounded_time(self):
        self.owned_vm(self.host_a)
        refresh_instance_database(self.host_a)
        InstanceTombstone.objects.update(removed=timezone.now() - timedelta(days=31))

        self.on(self.host_a, [("vm", UUID)])
        refresh_instance_database(self.host_a)

        self.assertEqual(self.ownership(self.host_a), (False, []))
        self.assertFalse(InstanceTombstone.objects.exists())
        self.assertIn(("-", "host-a", f"VM vm ({UUID}): removed record expired"), self.rows())

    @override_settings(INSTANCE_OWNERSHIP_RETENTION_DAYS=30)
    def test_a_removed_record_expires_while_nothing_changes(self):
        self.owned_vm(self.host_a)
        refresh_instance_database(self.host_a)
        InstanceTombstone.objects.update(removed=timezone.now() - timedelta(days=31))

        refresh_instance_database(self.host_b)  # its VMs match the database

        self.assertFalse(InstanceTombstone.objects.exists())
        # the VM's history (found by UUID) has it
        self.assertTrue(Logs.objects.filter(instance_uuid=UUID, instance="vm", message__endswith="expired").exists())
        self.assertIn(("-", "host-a", f"VM vm ({UUID}): removed record expired"), self.rows())

    def test_deleted_users_are_skipped(self):
        self.owned_vm(self.host_a)
        refresh_instance_database(self.host_a)
        self.owner.delete()

        self.on(self.host_a, [("vm", UUID)])
        refresh_instance_database(self.host_a)

        self.assertEqual(self.ownership(self.host_a), (True, []))

    # a deleted compute's VMs keep running on the host: their owners wait in
    # tombstones as for a VM that disappeared, or follow a VM already on another compute
    def delete(self, compute):
        admin = get_user_model().objects.create_superuser("cd-admin", "cd@example.com", "pw")
        self.client.force_login(admin)
        self.client.post(reverse("compute_delete", args=[compute.id]))
        self.assertFalse(Compute.objects.filter(pk=compute.pk).exists())

    def test_a_host_added_again_gets_its_vms_back_with_their_owners(self):
        self.owned_vm(self.host_a)
        self.delete(self.host_a)
        tombstone = InstanceTombstone.objects.get()
        self.assertEqual((tombstone.owners[0]["user"], tombstone.host), (self.owner.id, "host-a"))
        self.assertEqual(self.rows(), [
            ("cd-admin", "-", "Login"),
            ("-", "host-a", f"VM vm ({UUID}): kept on the Removed VMs page"),
            ("cd-admin", "host-a", "Compute host-a (host-a.example): delete"),
        ])

        again = self.compute("host-a-again")
        self.on(again, [("vm", UUID)])
        refresh_instance_database(again)
        self.assertEqual(self.ownership(again), (True, [(self.owner, True, False, True)]))

    def test_a_vm_already_on_another_compute_keeps_its_owners_there(self):
        self.owned_vm(self.host_a)
        self.on(self.host_b, [("vm", UUID)])
        refresh_instance_database(self.host_b)  # listed on B too: a copy for now
        self.delete(self.host_a)
        self.assertEqual(self.ownership(self.host_b), (True, [(self.owner, True, False, True)]))
        self.assertFalse(InstanceTombstone.objects.exists())

    def test_the_api_delete_keeps_the_owners_too(self):
        self.owned_vm(self.host_a)
        api = APIClient()
        api.force_login(get_user_model().objects.create_superuser("cd-api", "cda@example.com", "pw"))
        self.assertEqual(api.delete(reverse("compute-detail", args=[self.host_a.id])).status_code, 204)
        self.assertEqual(InstanceTombstone.objects.get().owners[0]["user"], self.owner.id)

    def test_a_compute_in_use_is_not_deleted(self):
        # a reconcile, VM operation or job holds it: the delete waits for none of them
        vm = self.owned_vm(self.host_a)
        claims.admit({claims.compute_key(self.host_a.id): Claim.SHARED}, holder="192.0.2.30:1:1")
        admin = get_user_model().objects.create_superuser("cd-busy", "cdb@example.com", "pw")
        self.client.force_login(admin)
        api = APIClient()
        api.force_login(admin)
        url = reverse("compute_delete", args=[self.host_a.id])
        self.assertRedirects(self.client.post(url, HTTP_REFERER=f"http://testserver{url}"), url,
                             fetch_redirect_response=False)
        self.assertEqual(api.delete(reverse("compute-detail", args=[self.host_a.id])).status_code, 409)
        self.assertTrue(Compute.objects.filter(pk=self.host_a.pk).exists())
        self.assertEqual(list(vm.userinstance_set.values_list("user", flat=True)), [self.owner.id])
        self.assertFalse(InstanceTombstone.objects.exists())
