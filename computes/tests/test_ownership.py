"""Ownership survives a VM's temporary disappearance or an out-of-band move."""

from datetime import timedelta
from unittest.mock import MagicMock

from accounts.models import UserInstance
from computes.models import Compute
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

UUID = "44444444-4444-4444-4444-444444444444"


class Domain:
    def __init__(self, name, uuid):
        self._name, self._uuid = name, uuid

    def name(self):
        return self._name

    def UUIDString(self):
        return self._uuid


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
        vm = Instance.objects.create(compute=compute, name="vm", uuid=UUID, is_template=True)
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
            ("-", "host-a", f"VM vm ({UUID}): owners kept on the Removed VMs page"),
            ("-", "host-a", f"VM vm ({UUID}): owners restored"),
        ])

    def test_an_ownerless_vm_leaves_a_row(self):
        Instance.objects.create(compute=self.host_a, name="vm", uuid=UUID)
        refresh_instance_database(self.host_a)
        self.assertEqual(self.rows(), [("-", "host-a", f"VM vm ({UUID}): left the panel (no owners)")])

    def test_move_seen_on_the_new_host_first(self):
        self.owned_vm(self.host_a)
        self.on(self.host_a, [("vm", UUID)])
        self.on(self.host_b, [("vm", UUID)])
        refresh_instance_database(self.host_b)  # still listed on A: a copy for now
        self.on(self.host_a, [])
        refresh_instance_database(self.host_a)  # gone from A: it moved to B

        self.assertEqual(self.ownership(self.host_b), (True, [(self.owner, True, False, True)]))
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

    @override_settings(INSTANCE_OWNERSHIP_RETENTION_DAYS=30)
    def test_ownership_is_kept_for_a_bounded_time(self):
        self.owned_vm(self.host_a)
        refresh_instance_database(self.host_a)
        InstanceTombstone.objects.update(removed=timezone.now() - timedelta(days=31))

        self.on(self.host_a, [("vm", UUID)])
        refresh_instance_database(self.host_a)

        self.assertEqual(self.ownership(self.host_a), (False, []))
        self.assertFalse(InstanceTombstone.objects.exists())
        self.assertIn(("-", "-", f"VM vm ({UUID}): removed record expired"), self.rows())

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
            ("-", "host-a", f"VM vm ({UUID}): owners kept on the Removed VMs page"),
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
