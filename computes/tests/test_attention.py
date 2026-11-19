"""The box above the Computes page's hosts: what wants a look, each with a link to where it is handled."""

import datetime
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from libvirt import libvirtError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from computes import views
from computes.models import Compute
from instances.models import Instance
from operations.models import Operation
from operations.utils import say
from vmbackups.models import Backup, BackupPolicy, BackupRun, BackupTarget
from vmbackups.schedule import IN_MAINTENANCE, NOT_STARTED
from vrtManager.hostdetails import wvmHostDetails

NOW = timezone.now()


class AttentionBoxTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("at-admin", "at@example.com", "pw")
        self.client.force_login(self.admin)
        self.up = Compute.objects.create(name="up", hostname="192.0.2.1", login="wvc", password="", type=1,
                                         host_uuid="11111111-0000-0000-0000-000000000000")
        self.down = Compute.objects.create(name="down", hostname="192.0.2.2", login="wvc", password="", type=1,
                                           host_uuid="22222222-0000-0000-0000-000000000000")
        self.vm = Instance.objects.create(compute=self.up, name="vm1", uuid="33333333-0000-4000-8000-000000000001")
        self.addCleanup(lambda: [read.join(5) for read in views._reading.values()])  # none left for the next test

    def read(self, compute):
        return (False, "refused", None, "") if compute.name == "down" else (True, None, None, "")

    def page(self, pools=(), snapshots=()):
        with patch("computes.views._read_host", side_effect=self.read), patch(
                "computes.views._read_attention", return_value={"pools": list(pools), "snapshots": list(snapshots)}):
            return self.client.get(reverse("computes"))

    def test_nothing_to_look_at_shows_no_box(self):
        self.down.delete()
        self.assertNotContains(self.page(), "Needs attention")

    def test_hosts_pools_and_snapshots(self):
        page = self.page(pools=[{"name": "default", "percent": 91}], snapshots=[{"vm": "vm1", "count": 2}])
        self.assertContains(page, "Needs attention")
        self.assertContains(page, f'<a href="{reverse("overview", args=[self.down.pk])}">down</a>: not answering',
                            html=False)
        self.assertContains(page, reverse("storage", args=[self.up.pk, "default"]))
        self.assertContains(page, "91% full")
        self.assertContains(page, reverse("instances:instance", args=[self.vm.pk]) + "#snapshots")
        self.assertContains(page, "2 snapshots older than 30 days")

    def test_snapshots_slow_to_list_do_not_hold_the_page(self):
        slow = {"pools": [{"name": "default", "percent": 91}], "snapshots": []}
        with patch("computes.views._read_host", side_effect=self.read), patch("computes.views.ATTENTION_WAIT", 0.2), patch(
                "computes.views._read_attention", side_effect=lambda compute: time.sleep(1) or slow):
            started = time.monotonic()
            page = self.client.get(reverse("computes"))
            took = time.monotonic() - started
        self.assertLess(took, 0.9)
        self.assertEqual({c.name: c.status for c in page.context["computes"]}, {"up": True, "down": False})
        self.assertNotContains(page, "91% full")  # left out this time

    def test_backups_and_jobs(self):
        target = BackupTarget.objects.create(name="t")
        policy = BackupPolicy.objects.create(name="n", target=target, time=datetime.time(2), keep=1)

        def backup(state, days_ago=0, **fields):
            b = Backup.objects.create(target=target, instance=self.vm, vm_uuid=self.vm.uuid, vm_name="vm1",
                                      compute_name="up", state=state, **fields)
            Backup.objects.filter(pk=b.pk).update(created_at=NOW - datetime.timedelta(days=days_ago))

        backup(Backup.MISSING, days_ago=40)
        backup(Backup.READY, damage=say("x"))
        today = timezone.localdate()
        BackupRun.objects.create(policy=policy, instance=self.vm, day=today, state=BackupRun.SKIPPED, note=say(NOT_STARTED))
        BackupRun.objects.create(policy=policy, instance=self.vm, day=today - datetime.timedelta(days=1),
                                 state=BackupRun.SKIPPED, note=say(IN_MAINTENANCE))  # the operator's choice
        Operation.objects.create(kind="backup.verify", user=self.admin, username="at-admin", submission_key="k1",
                                 resource="r1", state=Operation.UNCERTAIN)
        for key, days_ago in (("k4", 0), ("k5", 8)):  # a backup job failed this week, one before
            Operation.objects.create(kind="backup.create", user=self.admin, username="at-admin", submission_key=key,
                                     resource=key, state=Operation.FAILED,
                                     finished_at=NOW - datetime.timedelta(days=days_ago))
        waiting = Operation.objects.create(kind="backup.verify", user=self.admin, username="at-admin",
                                           submission_key="k2", resource="r2", state=Operation.QUEUED)
        Operation.objects.filter(pk=waiting.pk).update(created_at=NOW - datetime.timedelta(hours=2))
        Operation.objects.create(kind="backup.verify", user=self.admin, username="at-admin", submission_key="k3",
                                 resource="r3", state=Operation.QUEUED)  # just queued
        self.down.delete()
        page = self.page()
        for text in ("1 backup failed in the last 7 days", "1 scheduled backup not taken in the last 7 days",
                     "1 backup missing from its target", "1 backup damaged", "1 job ended uncertain",
                     "1 job queued for over an hour"):
            self.assertContains(page, text)
        self.assertContains(page, reverse("operations:jobs") + "?kind=backup.create&amp;state=failed")
        self.assertContains(page, f'<a href="{reverse("vmbackups:policy", args=[policy.pk])}">n</a>: 1 scheduled')
        self.assertContains(page, reverse("vmbackups:index") + "?state=damaged")
        self.assertContains(page, reverse("operations:jobs") + "?state=uncertain")
        listed = self.client.get(reverse("vmbackups:index") + "?state=damaged")
        self.assertEqual([b.state for b in listed.context["rows"]], [Backup.READY])


class HostAttentionTests(TestCase):
    def test_full_pools_and_old_snapshots_of_the_host(self):
        def pool(name, capacity, allocation):
            return MagicMock(**{"name.return_value": name, "info.return_value": [2, capacity, allocation, 0]})

        def snapshot(days_ago):
            created = int((NOW - datetime.timedelta(days=days_ago)).timestamp())
            return MagicMock(**{"getXMLDesc.return_value": f"<domainsnapshot><creationTime>{created}</creationTime>"
                                                           "</domainsnapshot>"})

        def domain(name, *snapshots):
            return MagicMock(**{"name.return_value": name, "listAllSnapshots.return_value": list(snapshots)})

        host = wvmHostDetails.__new__(wvmHostDetails)
        gone = MagicMock(**{"info.side_effect": libvirtError("undefined meanwhile")})
        deleted = MagicMock(**{"getXMLDesc.side_effect": libvirtError("deleted meanwhile")})
        host.wvm = SimpleNamespace(
            listAllStoragePools=lambda flags: [pool("default", 100, 90), gone, pool("big", 100, 10), pool("empty", 0, 0)],
            listAllDomains=lambda flags: [domain("old", snapshot(40), deleted, snapshot(31), snapshot(1)),
                                          domain("new", snapshot(2))])
        self.assertEqual(host.get_attention(85, NOW - datetime.timedelta(days=30)),
                         {"pools": [{"name": "default", "percent": 90}], "snapshots": [{"vm": "old", "count": 2}]})
