"""The box above the Computes page's hosts: what wants a look, each with a link to where it is handled."""

import datetime
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from libvirt import VIR_DOMAIN_XML_INACTIVE, VIR_ERR_NO_DOMAIN, libvirtError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from lxml import html

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

    def page(self, pools=(), snapshots=(), needs=None, read_needs=None, fresh=True):
        with patch("computes.views._read_host", side_effect=self.read), patch(
                "computes.views._read_attention", return_value={"pools": list(pools), "snapshots": list(snapshots)}), \
                patch("computes.views._read_needs", side_effect=read_needs or (lambda compute: (needs or {}).get(compute.name))):
            if fresh:  # no read of what VMs need kept from another test
                views._reading.clear()
            return self.client.get(reverse("computes"))

    def test_what_vms_need_is_read_on_each_load_the_last_standing_in_when_late(self):
        self.down.delete()
        Compute.objects.create(name="up2", hostname="192.0.2.3", login="wvc", password="", type=1,
                               host_uuid="44444444-0000-0000-0000-000000000000")
        none = {"networks": [], "filters": [], "secrets": [], "usages": []}
        lacking = {"up": {"uses": {**none, "networks": ["lab"]}, "has": {**none, "networks": ["lab"], "filters": {}}},
                   "up2": {"uses": none, "has": {**none, "filters": {}}}}
        fixed = {**lacking, "up2": {"uses": none, "has": {**none, "networks": ["lab"], "filters": {}}}}
        held = threading.Event()
        self.addCleanup(held.set)

        def settle():  # every read of the load ended: the next load starts its own
            held.set()
            for read in list(views._reading.values()):
                read.join(5)
            held.clear()

        def text(**kwargs):
            page = self.page(fresh=False, **kwargs)
            settle()
            return " ".join(html.fromstring(page.content).text_content().split())

        def late(compute):  # a read that outlasts the wait, then says the network is added
            held.wait(5)
            return fixed.get(compute.name)

        self.page(needs=lacking)
        settle()
        self.assertNotIn("could not migrate", text(needs=fixed))  # the network added: told at the next load
        # a host whose listing could not be read: the others still count
        unread = {**lacking, "up2": {"uses": none, "has": {**none, "networks": None, "filters": {}, "secrets": None,
                                                           "usages": None}}}
        self.assertNotIn("could not migrate", text(needs=unread))
        secrets_unread = {**lacking, "up2": {"uses": none, "has": {**none, "filters": {}, "secrets": None, "usages": None}}}
        self.assertIn("could not migrate here: no active network lab", text(needs=secrets_unread))

        # a late read: the last stands in, waited for NEEDS_GRACE only, not ATTENTION_WAIT
        self.assertIn("could not migrate", text(needs=lacking))
        with patch("computes.views.NEEDS_GRACE", 0.1), patch("computes.views.ATTENTION_WAIT", 5):
            began = time.monotonic()
            page = self.page(fresh=False, read_needs=late)
            self.assertLess(time.monotonic() - began, 2)
        settle()
        self.assertContains(page, "could not migrate")

        # a host that stopped answering: its stand-in, with the warning, is not told, nor waited for
        self.assertIn("could not migrate", text(needs=lacking))
        with patch.object(self, "read", lambda compute: (False, "refused", None, "") if compute.name == "up2"
                          else (True, None, None, "")), patch("computes.views.NEEDS_GRACE", 5):
            began = time.monotonic()  # only the silent host's read is late: it would be waited 5 s
            page = self.page(fresh=False, read_needs=lambda c: late(c) if c.name == "up2" else lacking.get(c.name))
            self.assertLess(time.monotonic() - began, 2)
        settle()
        shown = " ".join(html.fromstring(page.content).text_content().split())
        self.assertIn("up2: not answering", shown)
        self.assertNotIn("could not migrate", shown)

        # a read that failed leaves no stand-in: a late read after it tells no older warning
        self.assertIn("could not migrate", text(needs=lacking))
        text(needs={})  # this load's read fails (None)
        with patch("computes.views.ATTENTION_WAIT", 0.1):
            page = self.page(fresh=False, read_needs=late)
        settle()
        self.assertNotContains(page, "could not migrate")

    def test_what_a_vm_could_not_find_on_another_host(self):
        # a network, a filter or a secret its VMs use that another host lacks, or a filter of other rules there
        self.down.delete()
        up2 = Compute.objects.create(name="up2", hostname="192.0.2.3", login="wvc", password="", type=1,
                                     host_uuid="44444444-0000-0000-0000-000000000000")
        none = {"networks": [], "filters": [], "secrets": [], "usages": []}
        needs = {"up": {"uses": {"networks": ["prod", "lab"], "filters": ["base", "web", "gone"], "secrets": ["s-1"],
                                 "usages": [("ceph", "client.vm")]},
                        "has": {"networks": ["prod", "lab"], "secrets": ["s-1"], "usages": [("ceph", "client.vm")],
                                "filters": {"web": "<filter name='web'/>", "base": "<filter name='base'/>"}}},
                 "up2": {"uses": none,
                         "has": {"networks": ["prod"], "secrets": [], "usages": [],
                                 "filters": {"web": "<filter name='web'><rule/></filter>", "gone": "<filter name='gone'/>"}}}}
        text = " ".join(html.fromstring(self.page(needs=needs).content).text_content().split())
        # "gone": up's VMs name it, up lacks it too: not another host's rules
        self.assertIn("up2: VMs of up could not migrate here: no active network lab; no network filter base; network "
                      "filter web with other rules; no secret client.vm, s-1", text)
        self.assertNotIn("VMs of up2", text)  # what up2's VMs use, up has
        Compute.objects.filter(pk=up2.pk).update(maintenance_since=timezone.now())  # no destination now
        self.assertNotIn("could not migrate", " ".join(html.fromstring(self.page(needs=needs).content).text_content().split()))

    def test_what_vms_need_is_read_apart_from_the_pools(self):
        # its read failing or slow hides no full pool; it reads the host's migration_needs
        page = self.page(pools=[{"name": "default", "percent": 91}], needs={})
        self.assertContains(page, "91% full")
        late = threading.Event()
        with patch("computes.views.ATTENTION_WAIT", 0.2):
            page = self.page(pools=[{"name": "default", "percent": 91}], read_needs=lambda compute: late.wait(5) and None)
        late.set()
        self.assertContains(page, "91% full")
        compute = SimpleNamespace(status=True, proxy=MagicMock(**{"migration_needs.return_value": {"uses": {}}}))
        self.assertEqual(views._read_needs(compute), {"uses": {}})
        compute.proxy.migration_needs.side_effect = libvirtError("refused")
        self.assertIsNone(views._read_needs(compute))

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

    def test_what_the_hosts_vms_need_of_another_host(self):
        # its VMs' networks, filters (with those they reference) and secrets, of their running definition and the
        # one for the next start; its active networks, filters and secrets
        def domain(live, config=None):
            xml = {0: live, VIR_DOMAIN_XML_INACTIVE: config or live}
            return MagicMock(**{"XMLDesc.side_effect": lambda flags: xml[flags], "isPersistent.return_value": config is not None})

        def nwfilter(name, rules, refs=()):
            refs = "".join(f"<filterref filter='{ref}'/>" for ref in refs)
            return MagicMock(**{"name.return_value": name,
                                "XMLDesc.return_value": f"<filter name='{name}'><uuid>u-{name}</uuid>{rules}{refs}</filter>"})

        def nic(network, filterref=""):
            return (f"<interface type='network'><source network='{network}'/>"
                    f"{f'<filterref filter={chr(39)}{filterref}{chr(39)}/>' if filterref else ''}</interface>")

        host = wvmHostDetails.__new__(wvmHostDetails)
        gone = MagicMock(**{"XMLDesc.side_effect": libvirtError("gone meanwhile")})
        gone.XMLDesc.side_effect.get_error_code = lambda: VIR_ERR_NO_DOMAIN
        secret = MagicMock(**{"UUIDString.return_value": "S-2", "XMLDesc.return_value":
                              "<secret><usage type='ceph'><name>client.other</name></usage></secret>"})
        host.wvm = SimpleNamespace(
            listAllDomains=lambda flags=0: [gone, domain(
                f"<domain><devices>{nic('prod', 'web')}<disk><source><auth><secret type='ceph' uuid='S-1'/></auth>"
                "</source></disk><disk><source><auth><secret type='ceph' usage='client.vm'/></auth></source></disk>"
                "</devices></domain>",
                f"<domain><devices>{nic('lab')}</devices></domain>")],  # lab: at the next start
            listAllNetworks=lambda flags=0: [MagicMock(**{"name.return_value": "prod"})] if flags else [],
            listAllNWFilters=lambda flags=0: [nwfilter("web", "<rule/>", ["base"]), nwfilter("base", "<rule x='1'/>")],
            listAllSecrets=lambda flags=0: [secret])
        self.assertEqual(host.migration_needs(), {
            "uses": {"networks": ["lab", "prod"], "filters": ["base", "web"], "secrets": ["s-1"],
                     "usages": [("ceph", "client.vm")]},
            "has": {"networks": ["prod"], "secrets": ["s-2"], "usages": [("ceph", "client.other")],
                    "filters": {"web": "<filter name=\"web\"><rule/><filterref filter=\"base\"/></filter>",
                                "base": "<filter name=\"base\"><rule x=\"1\"/></filter>"}}})

    def test_a_listing_that_cannot_be_read_is_none_and_the_others_count(self):
        host = wvmHostDetails.__new__(wvmHostDetails)
        refused = MagicMock(side_effect=libvirtError("secrets driver down"))
        host.wvm = SimpleNamespace(listAllDomains=lambda flags=0: [], listAllNWFilters=lambda flags=0: [],
                                   listAllSecrets=refused,
                                   listAllNetworks=lambda flags=0: [MagicMock(**{"name.return_value": "prod"})])
        has = host.migration_needs()["has"]
        self.assertEqual((has["networks"], has["filters"], has["secrets"], has["usages"]), (["prod"], {}, None, None))

    def test_a_host_whose_vms_cannot_be_listed_is_still_a_destination(self):
        host = wvmHostDetails.__new__(wvmHostDetails)
        host.wvm = SimpleNamespace(listAllDomains=MagicMock(side_effect=libvirtError("refused")),
                                   listAllNWFilters=lambda flags=0: [], listAllSecrets=lambda flags=0: [],
                                   listAllNetworks=lambda flags=0: [MagicMock(**{"name.return_value": "prod"})])
        needs = host.migration_needs()
        self.assertIsNone(needs["uses"])
        self.assertEqual(needs["has"]["networks"], ["prod"])
        none = {"networks": [], "filters": [], "secrets": [], "usages": []}
        source = MagicMock(status=True, maintenance=False, needs={"uses": {**none, "networks": ["lab"]},
                                                                         "has": {**none, "filters": {}}})
        target = MagicMock(status=True, maintenance=False, needs=needs)
        self.assertEqual([(t, s) for t, s, _what in views.lacking([source, target])], [(target, source)])

