"""Two reconciles of different computes decide the owners of the same UUID
one after the other: the move's restore sees the bury committed. SQLite's
IMMEDIATE transactions serialize them; PostgreSQL takes the ownership lock."""

import threading
import time
from unittest.mock import MagicMock, patch

from accounts.models import UserInstance
from computes import utils
from computes.models import Compute
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from instances.models import Instance, InstanceTombstone

UUID = "44444444-4444-4444-4444-444444444444"


class Domain:
    def __init__(self, name, uuid):
        self._name, self._uuid = name, uuid

    def name(self):
        return self._name

    def UUIDString(self):
        return self._uuid


class OwnershipRaceTests(TransactionTestCase):
    def compute(self, name, domains):
        c = Compute.objects.create(name=name, hostname=f"{name}.example", login="", password="", type=1)
        c.__dict__["proxy"] = MagicMock()
        c.__dict__["status"] = True
        c.proxy.wvm.listAllDomains.return_value = [Domain(n, u) for n, u in domains]
        return c

    def test_move_seen_by_both_reconciles_at_once(self):
        a = self.compute("host-a", [])                 # the VM left A (virsh migrate)
        self.race(a, lambda: utils.refresh_instance_database(a))

    def test_a_compute_delete_and_a_reconcile_at_once(self):
        a = self.compute("host-a", [("vm", UUID)])     # deleted while B sees the VM
        self.race(a, a.delete)

    def race(self, a, decide_a):
        """decide_a buries the VM's owners on A and waits with its transaction
        open while B's reconcile finds the VM; B must restore them."""
        owner = get_user_model().objects.create_user("owner", password="pw")
        b = self.compute("host-b", [("vm", UUID)])
        vm = Instance.objects.create(compute=a, name="vm", uuid=UUID)
        UserInstance.objects.create(instance=vm, user=owner, is_change=True)

        buried, go = threading.Event(), threading.Event()
        real_forget = utils.forget

        def slow_forget(inst):
            real_forget(inst)  # B's row does not exist yet: owners go to a tombstone
            buried.set()
            go.wait(10)        # A's transaction stays open here

        def run(decide):
            try:
                decide()
            finally:
                connection.close()

        with patch.object(utils, "forget", slow_forget):
            ta = threading.Thread(target=run, args=(decide_a,))
            ta.start()
            self.assertTrue(buried.wait(10))
            tb = threading.Thread(target=run, args=(lambda: utils.refresh_instance_database(b),))
            tb.start()
            time.sleep(1)  # B would decide now if nothing held it
            go.set()
            ta.join(30)
            tb.join(30)

        on_b = Instance.objects.get(compute=b, uuid=UUID)
        self.assertEqual(list(on_b.userinstance_set.values_list("user__username", flat=True)), ["owner"])
        self.assertFalse(InstanceTombstone.objects.exists())
